import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import pandas as pd
import requests
import threading
import time


class TextCorrectorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("文案修正工具 - LM Studio")
        self.root.geometry("1000x700")

        self.df = None
        self.current_row = 0
        self.api_url = "http://localhost:1234/v1/chat/completions"
        self.model_name = "gemma-4-e4b-it-ultra-uncensored-heretic"

        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0

        self._setup_ui()

    def _setup_ui(self):
        config_frame = ttk.LabelFrame(self.root, text="配置", padding=10)
        config_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(config_frame, text="API地址:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.api_url_var = tk.StringVar(value=self.api_url)
        ttk.Entry(config_frame, textvariable=self.api_url_var, width=50).grid(row=0, column=1, padx=5)

        ttk.Label(config_frame, text="模型名称:").grid(row=0, column=2, sticky=tk.W, padx=5)
        self.model_var = tk.StringVar(value=self.model_name)
        ttk.Entry(config_frame, textvariable=self.model_var, width=30).grid(row=0, column=3, padx=5)

        file_frame = ttk.LabelFrame(self.root, text="文件操作", padding=10)
        file_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Button(file_frame, text="打开表格", command=self.load_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(file_frame, text="保存表格", command=self.save_file).pack(side=tk.LEFT, padx=5)
        self.file_label = ttk.Label(file_frame, text="未加载文件")
        self.file_label.pack(side=tk.LEFT, padx=20)

        nav_frame = ttk.Frame(self.root, padding=10)
        nav_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Button(nav_frame, text="上一行", command=self.prev_row).pack(side=tk.LEFT, padx=5)
        self.row_label = ttk.Label(nav_frame, text="第 0 / 0 行")
        self.row_label.pack(side=tk.LEFT, padx=20)
        ttk.Button(nav_frame, text="下一行", command=self.next_row).pack(side=tk.LEFT, padx=5)

        ttk.Label(nav_frame, text="跳转:").pack(side=tk.LEFT, padx=(20, 5))
        self.jump_var = tk.StringVar()
        ttk.Entry(nav_frame, textvariable=self.jump_var, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Button(nav_frame, text="GO", command=self.jump_to_row).pack(side=tk.LEFT, padx=5)

        token_frame = ttk.LabelFrame(self.root, text="Token消耗", padding=10)
        token_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(token_frame, text="输入Token:").pack(side=tk.LEFT, padx=10)
        self.prompt_token_label = ttk.Label(token_frame, text="0")
        self.prompt_token_label.pack(side=tk.LEFT, padx=5)

        ttk.Label(token_frame, text="输出Token:").pack(side=tk.LEFT, padx=20)
        self.completion_token_label = ttk.Label(token_frame, text="0")
        self.completion_token_label.pack(side=tk.LEFT, padx=5)

        ttk.Label(token_frame, text="总Token:").pack(side=tk.LEFT, padx=20)
        self.total_token_label = ttk.Label(token_frame, text="0")
        self.total_token_label.pack(side=tk.LEFT, padx=5)

        data_frame = ttk.LabelFrame(self.root, text="文案数据", padding=10)
        data_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        info_frame = ttk.Frame(data_frame)
        info_frame.pack(fill=tk.X, pady=5)

        ttk.Label(info_frame, text="视频标题:").grid(row=0, column=0, sticky=tk.W)
        self.title_var = tk.StringVar()
        ttk.Label(info_frame, textvariable=self.title_var, wraplength=800).grid(row=0, column=1, sticky=tk.W, padx=5)

        ttk.Label(data_frame, text="原始文案:").pack(anchor=tk.W)
        self.original_text = scrolledtext.ScrolledText(data_frame, height=8, wrap=tk.WORD, state=tk.DISABLED)
        self.original_text.pack(fill=tk.X, pady=5)

        btn_frame = ttk.Frame(data_frame)
        btn_frame.pack(fill=tk.X, pady=5)

        self.correct_btn = ttk.Button(btn_frame, text="调用AI修正", command=self.correct_text)
        self.correct_btn.pack(side=tk.LEFT, padx=5)

        self.batch_btn = ttk.Button(btn_frame, text="批量修正全部", command=self.batch_correct)
        self.batch_btn.pack(side=tk.LEFT, padx=5)

        ttk.Button(btn_frame, text="保存到当前行", command=self.apply_correction).pack(side=tk.LEFT, padx=5)

        ttk.Label(data_frame, text="修正后文案:").pack(anchor=tk.W)
        self.corrected_text = scrolledtext.ScrolledText(data_frame, height=8, wrap=tk.WORD)
        self.corrected_text.pack(fill=tk.X, pady=5)

        self.progress = ttk.Progressbar(self.root, mode='determinate')
        self.progress.pack(fill=tk.X, padx=10, pady=5)

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.status_var).pack(anchor=tk.W, padx=10, pady=5)

    def load_file(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("Excel/CSV文件", "*.xlsx *.xls *.csv"), ("所有文件", "*.*")]
        )
        if not file_path:
            return

        try:
            if file_path.endswith('.csv'):
                self.df = pd.read_csv(file_path, encoding='utf-8')
            else:
                self.df = pd.read_excel(file_path)

            self.total_prompt_tokens = 0
            self.total_completion_tokens = 0
            self.total_tokens = 0
            self.update_token_display()

            self.current_row = 0
            self.file_label.config(text=f"已加载: {file_path} ({len(self.df)} 行)")
            self.update_display()
            self.status_var.set(f"成功加载 {len(self.df)} 行数据")
        except Exception as e:
            messagebox.showerror("错误", f"加载文件失败:\n{str(e)}")

    def save_file(self):
        if self.df is None:
            messagebox.showwarning("警告", "请先加载文件")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel文件", "*.xlsx"), ("CSV文件", "*.csv")]
        )
        if not file_path:
            return

        try:
            if file_path.endswith('.csv'):
                self.df.to_csv(file_path, index=False, encoding='utf-8-sig')
            else:
                self.df.to_excel(file_path, index=False)
            self.status_var.set(f"已保存到: {file_path}")
            messagebox.showinfo("成功", "文件保存成功!")
        except Exception as e:
            messagebox.showerror("错误", f"保存文件失败:\n{str(e)}")

    def update_display(self):
        if self.df is None or len(self.df) == 0:
            return

        total = len(self.df)
        self.row_label.config(text=f"第 {self.current_row + 1} / {total} 行")

        if '视频标题' in self.df.columns:
            self.title_var.set(str(self.df.iloc[self.current_row]['视频标题']))
        else:
            self.title_var.set("无标题")

        if '视频文案' in self.df.columns:
            original = str(self.df.iloc[self.current_row]['视频文案'])
            self.original_text.config(state=tk.NORMAL)
            self.original_text.delete(1.0, tk.END)
            self.original_text.insert(1.0, original)
            self.original_text.config(state=tk.DISABLED)

        if '修正后文案' in self.df.columns:
            corrected = str(self.df.iloc[self.current_row]['修正后文案'])
            if corrected != 'nan' and corrected:
                self.corrected_text.delete(1.0, tk.END)
                self.corrected_text.insert(1.0, corrected)

    def prev_row(self):
        if self.df is None:
            return
        if self.current_row > 0:
            self.current_row -= 1
            self.update_display()

    def next_row(self):
        if self.df is None:
            return
        if self.current_row < len(self.df) - 1:
            self.current_row += 1
            self.update_display()

    def jump_to_row(self):
        if self.df is None:
            return
        try:
            row = int(self.jump_var.get()) - 1
            if 0 <= row < len(self.df):
                self.current_row = row
                self.update_display()
            else:
                messagebox.showwarning("警告", f"行号应在 1-{len(self.df)} 之间")
        except ValueError:
            messagebox.showwarning("警告", "请输入有效数字")

    def call_ai_api(self, text):
        """调用LM Studio API - 每次都是独立对话，返回文案和token消耗"""
        api_url = self.api_url_var.get()
        model = self.model_var.get()

        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": f"请处理以下文案，只返回处理和的结果:\n\n{text}"}
            ],
            "temperature": 0.3,
            "max_tokens": 100000,
            "stream": False
        }
        timeout = 60000
        try:
            response = requests.post(
                api_url,
                json=payload,
                timeout=timeout,
                headers={"Connection": "keep-alive"}
            )
            response.raise_for_status()

            result = response.json()
            corrected = result['choices'][0]['message']['content'].strip()
            usage = result.get('usage', {})

            return {
                'corrected': corrected,
                'prompt_tokens': usage.get('prompt_tokens', 0),
                'completion_tokens': usage.get('completion_tokens', 0),
                'total_tokens': usage.get('total_tokens', 0)
            }
        except requests.exceptions.ReadTimeout:
            raise Exception("请求超时！模型生成时间过长，请增加超时时间或缩短文案")

    def correct_text(self):
        if self.df is None:
            messagebox.showwarning("警告", "请先加载文件")
            return

        text = self.original_text.get(1.0, tk.END).strip()
        if not text or len(text) < 10:
            messagebox.showwarning("警告", "文案内容太短，无需修正")
            return

        self.correct_btn.config(state=tk.DISABLED)
        self.status_var.set("正在调用AI修正...")

        def run_correction():
            try:
                result = self.call_ai_api(text)
                self.root.after(0, lambda: self.show_corrected_text(result))
            except Exception as e:
                self.root.after(0, lambda: self.show_error(str(e)))

        threading.Thread(target=run_correction, daemon=True).start()

    def show_corrected_text(self, result):
        self.corrected_text.delete(1.0, tk.END)
        self.corrected_text.insert(1.0, result['corrected'])
        self.correct_btn.config(state=tk.NORMAL)
        self.status_var.set(f"修正完成 (第 {self.current_row + 1} 行) - 消耗 {result['total_tokens']} tokens")

    def show_error(self, error):
        self.corrected_text.delete(1.0, tk.END)
        self.corrected_text.insert(1.0, f"错误: {error}")
        self.correct_btn.config(state=tk.NORMAL)
        self.status_var.set("修正失败")

    def apply_correction(self):
        if self.df is None:
            return

        corrected = self.corrected_text.get(1.0, tk.END).strip()
        if not corrected:
            messagebox.showwarning("警告", "没有可应用的修正内容")
            return

        if '修正后文案' not in self.df.columns:
            self.df['修正后文案'] = ''
        if '输入Token' not in self.df.columns:
            self.df['输入Token'] = 0
        if '输出Token' not in self.df.columns:
            self.df['输出Token'] = 0
        if '总Token' not in self.df.columns:
            self.df['总Token'] = 0

        self.df.at[self.current_row, '修正后文案'] = corrected

        self.status_var.set(f"已保存修正到第 {self.current_row + 1} 行")

    def update_token_display(self):
        self.prompt_token_label.config(text=f"{self.total_prompt_tokens}")
        self.completion_token_label.config(text=f"{self.total_completion_tokens}")
        self.total_token_label.config(text=f"{self.total_tokens}")

    def batch_correct(self):
        if self.df is None:
            messagebox.showwarning("警告", "请先加载文件")
            return

        if '视频文案' not in self.df.columns:
            messagebox.showwarning("警告", "表格中没有'视频文案'列")
            return

        if not messagebox.askyesno("确认", f"将批量修正 {len(self.df)} 行文案，这可能需要较长时间。是否继续?"):
            return

        self.batch_btn.config(state=tk.DISABLED)
        self.correct_btn.config(state=tk.DISABLED)

        if '修正后文案' not in self.df.columns:
            self.df['修正后文案'] = ''
        if '输入Token' not in self.df.columns:
            self.df['输入Token'] = 0
        if '输出Token' not in self.df.columns:
            self.df['输出Token'] = 0
        if '总Token' not in self.df.columns:
            self.df['总Token'] = 0

        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0

        def run_batch():
            total = len(self.df)
            for i in range(total):
                text = str(self.df.iloc[i]['视频文案'])
                if len(text) < 10:
                    self.root.after(0, lambda i=i: self.update_progress(i + 1, total, f"跳过第 {i+1} 行 (内容太短)"))
                    continue

                try:
                    result = self.call_ai_api(text)
                    self.df.at[i, '修正后文案'] = result['corrected']
                    self.df.at[i, '输入Token'] = result['prompt_tokens']
                    self.df.at[i, '输出Token'] = result['completion_tokens']
                    self.df.at[i, '总Token'] = result['total_tokens']

                    self.total_prompt_tokens += result['prompt_tokens']
                    self.total_completion_tokens += result['completion_tokens']
                    self.total_tokens += result['total_tokens']

                    self.root.after(0, lambda: self.update_token_display())
                    self.root.after(0, lambda i=i: self.update_progress(i + 1, total, f"已修正第 {i+1} 行"))
                except Exception as e:
                    self.root.after(0, lambda i=i, e=str(e): self.update_progress(i + 1, total, f"第 {i+1} 行失败: {e}"))

                time.sleep(1)

            self.root.after(0, self.batch_complete)

        threading.Thread(target=run_batch, daemon=True).start()

    def update_progress(self, current, total, message):
        self.progress['value'] = (current / total) * 100
        self.status_var.set(f"{message} ({current}/{total})")

    def batch_complete(self):
        self.batch_btn.config(state=tk.NORMAL)
        self.correct_btn.config(state=tk.NORMAL)
        self.progress['value'] = 100
        self.update_token_display()
        self.status_var.set(f"批量修正完成! 共消耗 {self.total_tokens} tokens。记得保存文件。")
        messagebox.showinfo("完成", f"批量修正完成!\n总消耗: {self.total_tokens} tokens\n请检查并保存文件。")
        self.update_display()


def main():
    root = tk.Tk()
    app = TextCorrectorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()