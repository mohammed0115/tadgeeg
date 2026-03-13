import subprocess
import sys

script = """
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'finai_backend.settings')

import django
django.setup()

from django.contrib.auth.models import User

user, created = User.objects.get_or_create(
    username='demo@finai.sa',
    defaults={'email': 'demo@finai.sa'}
)
user.set_password('DemoDashboard123!')
user.save()

print('✅ User Created!' if created else '✅ User Updated!')
print('   Email: demo@finai.sa')
print('   Password: DemoDashboard123!')
"""

result = subprocess.run(
    ['/home/mohamed/Desktop/tadgeeg/.venv/bin/python', '-c', script],
    cwd='/home/mohamed/Desktop/tadgeeg',
    capture_output=True,
    text=True
)

print(result.stdout)
if result.stderr:
    print("Errors:", result.stderr)
print(f"Exit code: {result.returncode}")
