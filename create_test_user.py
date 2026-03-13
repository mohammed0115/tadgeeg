#!/usr/bin/env python
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'finai_backend.settings')
django.setup()

from django.contrib.auth.models import User

try:
    # Check if user already exists
    if User.objects.filter(username='demo@finai.sa').exists():
        user = User.objects.get(username='demo@finai.sa')
        user.set_password('DemoDashboard123!')
        user.save()
        print(f"✅ Password updated for existing user: {user.email}")
    else:
        user = User.objects.create_user(
            username='demo@finai.sa',
            email='demo@finai.sa',
            password='DemoDashboard123!'
        )
        print(f"✅ User created successfully!")
        print(f"   Username: {user.username}")
        print(f"   Email: {user.email}")
        print(f"   ID: {user.id}")
        print(f"   Created: {user.date_joined}")
        
    print(f"\n📧 Login Credentials:")
    print(f"   Email: demo@finai.sa")
    print(f"   Password: DemoDashboard123!")
    
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
