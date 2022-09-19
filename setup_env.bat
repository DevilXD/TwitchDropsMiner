@set /p "choice=Install PyInstaller so you can build an EXEcutable? (y/n) "
python -m venv env
%CD%/env/scripts/pip install wheel
%CD%/env/scripts/pip install -r %CD%/requirements.txt
if "%choice%" == "y" %CD%/env/scripts/pip install pyinstaller
%CD%/env/scripts/python %CD%/env/scripts/pywin32_postinstall.py -install -silent
