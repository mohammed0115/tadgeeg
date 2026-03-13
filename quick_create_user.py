import os
import sys

# Set up Django
os.environ['DJANGO_SETTINGS_MODULE'] = 'finai_backend.settings'
os.chdir('/home/mohamed/Desktop/tadgeeg')
sys.path.insert(0, '/home/mohamed/Desktop/tadgeeg')

import django
django.setup()

# Now create the user
from django.contrib.auth.models import User

username = 'demo@finai.sa'
email = 'demo@finai.sa'
password = 'DemoDashboard123!'

user, created = User.objects.get_or_create(
    username=username,
    defaults={'email': email}
)

user.set_password(password)
user.save()

print("✅ USER CREATED!" if created else "✅ USER UPDATED!")
print(f"📧 Email: {email}")
print(f"🔐 Password: {password}")
print(f"🔗 Login URL: http://localhost:8000/login/")
print(f"📊 Dashboard: http://localhost:8000/dashboard/")
