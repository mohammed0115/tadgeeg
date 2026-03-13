#!/usr/bin/env python3
import subprocess
import os

os.chdir('/home/mohamed/Desktop/tadgeeg')

# Run the Django management command
proc = subprocess.Popen(
    ['/home/mohamed/Desktop/tadgeeg/.venv/bin/python', 'manage.py', 'create_demo_user'],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

stdout, stderr = proc.communicate()

# Print results
if stdout:
    print(stdout)
if stderr:
    print("STDERR:", stderr)

exit(proc.returncode)
