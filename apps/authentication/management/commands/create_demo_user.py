from django.core.management.base import BaseCommand
from apps.authentication.models import User


class Command(BaseCommand):
    help = 'Create a demo user for testing the dashboard'

    def handle(self, *args, **options):
        email = 'demo@finai.sa'
        password = 'DemoDashboard123!'
        full_name = 'Demo Dashboard'
        
        try:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={'full_name': full_name, 'role': User.Role.ADMIN, 'is_active': True}
            )
            
            user.set_password(password)
            user.is_active = True  # Ensure account is active
            user.save()
            
            if created:
                self.stdout.write(self.style.SUCCESS('✅ User Created Successfully!'))
            else:
                self.stdout.write(self.style.SUCCESS('✅ User Updated (password reset)!'))
                
            self.stdout.write('\n📧 Login Credentials:')
            self.stdout.write(f'   Email: {email}')
            self.stdout.write(f'   Password: {password}')
            self.stdout.write(f'   Role: Admin')
            self.stdout.write('\n🔗 Access dashboard at: http://localhost:8000/dashboard/')
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Error: {e}'))
