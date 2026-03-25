"""Organization team management URLs."""

from django.urls import path

from . import api_views

urlpatterns = [
    path("team/members/", api_views.VendorTeamMemberListView.as_view(), name="team-members"),
    path("team/members/<uuid:pk>/", api_views.VendorTeamMemberDetailView.as_view(), name="team-member-detail"),
    path("team/invitations/", api_views.VendorInvitationListView.as_view(), name="team-invitations"),
    path("team/invitations/<str:pk>/", api_views.VendorInvitationActionView.as_view(), name="team-invitation-detail"),
    path("team/invitations/<str:pk>/resend/", api_views.VendorInvitationActionView.as_view(), name="team-invitation-resend"),
    path("team/invite/", api_views.VendorInviteView.as_view(), name="team-invite"),
]
