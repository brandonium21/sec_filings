import sys
from cx_Freeze import setup, Executable
import requests

# Dependencies are automatically detected, but it might need fine tuning.
build_exe_options = {"packages": ["os"], "includes": ["requests", "blist", "BeautifulSoup"], 'include_files' : [(requests.certs.where(), 'cacert.pem')]}

# GUI applications require a different base on Windows (the default is for a
# console application).
base = None
if sys.platform == "win32":
    base = "Win32GUI"

setup(  name = "SEC Filings Violation Search",
        version = "0.1",
        description = "Search for Violations in SEC filings for companies",
        options = {"build_exe": build_exe_options},
        executables = [Executable("app.py", base=base)])