# Python / Conda / PaddleOCR 常用命令总结

## 1. 查看 Conda 是否安装成功

```powershell
conda --version
```

查看已经安装的 conda 环境：

```powershell
conda env list
```

或者：

```powershell
conda info --envs
```

---

## 2. 创建 Python 虚拟环境

创建一个名为 `rag` 的环境，并指定 Python 版本为 3.11：

```powershell
conda create -n rag python=3.11
```

如果提示：

```text
Do you accept the Terms of Service?
[(a)ccept/(r)eject/(v)iew]:
```

输入：

```powershell
a
```

如果提示：

```text
Proceed ([y]/n)?
```

输入：

```powershell
y
```

---

## 3. 激活 rag 环境

```powershell
conda activate rag
```

激活成功后，命令行前面会出现：

```text
(rag)
```

例如：

```powershell
(rag) PS D:\project\rag\reg>
```

退出当前环境：

```powershell
conda deactivate
```

---

## 4. 进入项目目录

进入你的 Python 项目目录：

```powershell
cd D:\project\rag\reg
```

---

## 5. 安装项目依赖

如果项目中有 `requirements.txt`，执行：

```powershell
python -m pip install -r requirements.txt
```

推荐的 `requirements.txt` 内容：

```txt
pandas
langchain-core
langchain-community
pypdf
docx2txt
openpyxl
xlrd
paddleocr
```

---

## 6. 安装 PaddlePaddle CPU 版

建议 PaddlePaddle 单独安装：

```powershell
python -m pip install paddlepaddle -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
```

---

## 7. 安装 PaddleOCR

```powershell
python -m pip install paddleocr
```

---

## 8. 验证 PaddlePaddle 是否安装成功

```powershell
python -c "import paddle; paddle.utils.run_check(); print('paddle ok')"
```

如果看到类似输出：

```text
PaddlePaddle is installed successfully!
paddle ok
```

说明 PaddlePaddle 安装成功。

---

## 9. 验证 PaddleOCR 是否安装成功

```powershell
python -c "from paddleocr import PaddleOCR; print('paddleocr ok')"
```

如果输出：

```text
paddleocr ok
```

说明 PaddleOCR 安装成功。

---

## 10. 升级 pip，可选

```powershell
python -m pip install --upgrade pip
```

---

## 11. 运行 Python 程序

如果你的主程序文件叫 `parser.py`：

```powershell
python parser.py
```

如果你的主程序文件叫 `main.py`：

```powershell
python main.py
```

---

## 12. VS Code 中选择 rag 环境

在 VS Code 中按：

```text
Ctrl + Shift + P
```

搜索：

```text
Python: Select Interpreter
```

选择类似下面的解释器：

```text
conda env: rag
```

或者路径类似：

```text
C:\Users\Administrator\miniconda3\envs\rag\python.exe
```

---

## 13. 每次打开项目后的常用流程

以后每次打开 VS Code 或终端，按这个顺序执行：

```powershell
cd D:\project\rag\reg
conda activate rag
python parser.py
```

---

## 14. 第一次配置项目时的完整流程

第一次配置项目，可以按这个顺序执行：

```powershell
cd D:\project\rag\reg

conda activate rag

python -m pip install -r requirements.txt

python -m pip install paddlepaddle -i https://www.paddlepaddle.org.cn/packages/stable/cpu/

python -m pip install paddleocr

python -c "import paddle; paddle.utils.run_check(); print('paddle ok')"

python -c "from paddleocr import PaddleOCR; print('paddleocr ok')"

python parser.py
```

---

## 15. 注意事项

一定要看命令行前面是不是：

```text
(rag)
```

如果不是，说明你还没有进入 `rag` 环境。

需要先执行：

```powershell
conda activate rag
```

然后再安装依赖或运行程序。

不要在 `(base)` 环境里安装项目依赖，最好统一装到 `rag` 环境里。
