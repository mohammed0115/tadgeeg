#!/usr/bin/env python
"""
Create test user for FinAI dashboard
Usage: python create_test_user.py
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'finai_backend.settings')
sys.path.insert(0, '/home/mohamed/Desktop/tadgeeg')

django.setup()

from django.contrib.auth.models import User

def create_user():
    """Create or update test user"""
    try:
        username = 'demo@finai.sa'
        email = 'demo@finai.sa'
        password = 'DemoDashboard123!'
        
        user, created = User.objects.get_or_create(
            username=username,
            defaults={'email': email}
        )
        
        user.set_password(password)
        user.save()
        
        if created:
            print("✅ User Created Successfully!")
        else:
            print("✅ User Updated (password reset)!")
            
        print(f"\n📧 Login Credentials:")
        print(f"   Email: {email}")
        print(f"   Password: {password}")
        print(f"\n🔗 Access dashboard at: http://localhost:8000/dashboard/")
        
        return 0
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(create_user())
