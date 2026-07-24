import json
from django.contrib import admin
from django.db.models import Q
from django.urls import path, include
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from rest_framework.routers import DefaultRouter

# ==========================================
# 1 - IMPORTS
# ==========================================

# CRM UI Views
from crm.views import (
    crm_accounts_view, crm_archive_view, dashboard_view, leads_list_view,
    postal_code_lookup_view,
)

# FSM Views & APIs
from fsm.views import (
    jobs_board_view,
    live_fleet_view,
    EvidenceUploadView, 
    MobileClockInView, 
    MobileClockOutView,
    TrackLocationPingView,
    LiveFleetLocationsView,
    FieldJobActionView,
    FieldWorkActivityView,
    FieldIssueReportView,
    FieldIssueStatusView,
    FieldShiftView,
    field_job_view,
    field_operations_view,
)
from fsm.calendar_views import (
    calendar_job_update_view,
    calendar_jobs_view,
    calendar_options_view,
    job_calendar_view,
)

# Unified API ViewSets
from core.api.views import AccountViewSet, ContactViewSet, JobViewSet, PaymentMethodViewSet, PropertyViewSet, WorkerViewSet
from core.views import home_view, reports_view
from finance.views import (
    estimate_convert_view,
    finance_invoice_detail_view,
    finance_job_costing_view,
    finance_overview_view,
    finance_payment_settings_view,
    finance_sales_view,
)
from finance.billing_views import billing_overview_view, create_billing_portal_view, create_checkout_session_view, stripe_webhook_view
from organizations.models import Workspace
from organizations.views import admin_console_view, create_workspace_view, employee_profile_view, signup_view, verify_email_view, email_verification_pending_view
from organizations.passkeys import (
    passkey_authentication_options, passkey_authentication_verify,
    passkey_registration_options, passkey_registration_verify,
)
from workforce.views import employee_document_download_view, employee_photo_view, team_member_detail_view, workforce_view, work_activity_ledger_view
from chat.views import (
    chat_attach_job_view, chat_conversation_action_view, chat_inbox_view, chat_message_view,
    chat_push_subscribe_view, chat_push_unsubscribe_view, chat_service_worker_view,
    website_chat_launcher_view, website_chat_settings_view, website_chat_widget_view,
)


# ==========================================
# 2 - REST FRAMEWORK ROUTER
# ==========================================
router = DefaultRouter()
router.register(r'accounts', AccountViewSet, basename='api-account')
router.register(r'contacts', ContactViewSet, basename='api-contact')
router.register(r'properties', PropertyViewSet, basename='api-property')
router.register(r'payment-methods', PaymentMethodViewSet, basename='api-payment-method')
router.register(r'jobs', JobViewSet, basename='api-job')
router.register(r'workers', WorkerViewSet, basename='api-worker')


# ==========================================
# 3 - HELPER VIEWS
# ==========================================
@login_required
@require_POST
def switch_organization_view(request):
    """Updates the user's session cookie with their new active Organization ID"""
    try:
        data = json.loads(request.body)
        org_id = data.get('org_id')

        if request.user.is_superuser:
            workspace = Workspace.objects.filter(id=org_id).first()
        else:
            workspace = Workspace.objects.filter(
                Q(members__user=request.user, members__is_active=True) |
                Q(workers__user=request.user),
                id=org_id,
            ).distinct().first()

        if not workspace:
            return JsonResponse({'status': 'error', 'message': 'Organization not found.'}, status=404)

        request.session['active_org_id'] = str(workspace.id)
        return JsonResponse({'status': 'success', 'active_org_id': str(workspace.id)})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


# ==========================================
# 4 - URL PATTERNS
# ==========================================
urlpatterns = [
    # --- SYSTEM ---
    path('admin/', admin.site.urls),
    path('signup/', signup_view, name='signup'),
    path('verification-pending/', email_verification_pending_view, name='email_verification_pending'),
    path('verify-email/<str:token>/', verify_email_view, name='verify_email'),
    path('api/switch-org/', switch_organization_view, name='switch_org'),
    
    # --- WEB UI DASHBOARDS ---
    path('', home_view, name='marketing_home'),
    path('dashboard/', dashboard_view, name='dashboard'),
    path('leads/', leads_list_view, name='leads'),
    path('jobs/', jobs_board_view, name='jobs'),
    path('jobs/calendar/', job_calendar_view, name='job_calendar'),
    path('jobs/live-fleet/', live_fleet_view, name='live_fleet'),
    path('accounts/', crm_accounts_view, name='accounts'),
    path('contacts/', crm_accounts_view, {'section': 'contacts'}, name='contacts'),
    path('properties/', crm_accounts_view, {'section': 'properties'}, name='properties'),
    path('payment-methods/', crm_accounts_view, {'section': 'payment_methods'}, name='payment_methods'),
    path('crm/archive/', crm_archive_view, name='crm_archive'),
    path('finance/', finance_overview_view, name='finance'),
    path('finance/sales/', finance_sales_view, name='finance_sales'),
    path('finance/estimates/<int:estimate_id>/convert/', estimate_convert_view, name='finance_estimate_convert'),
    path('finance/invoices/<int:invoice_id>/', finance_invoice_detail_view, name='finance_invoice_detail'),
    path('finance/payment-settings/', finance_payment_settings_view, name='finance_payment_settings'),
    path('finance/job-costing/', finance_job_costing_view, name='finance_job_costing'),
    path('workforce/', workforce_view, name='workforce'),
    path('chat/', chat_inbox_view, name='chat_inbox'),
    path('chat/push/subscribe/', chat_push_subscribe_view, name='chat_push_subscribe'),
    path('chat/push/unsubscribe/', chat_push_unsubscribe_view, name='chat_push_unsubscribe'),
    path('chat/service-worker.js', chat_service_worker_view, name='chat_service_worker'),
    path('chat/<uuid:conversation_id>/', chat_inbox_view, name='chat_conversation'),
    path('chat/<uuid:conversation_id>/message/', chat_message_view, name='chat_message'),
    path('chat/<uuid:conversation_id>/attach-job/', chat_attach_job_view, name='chat_attach_job'),
    path('chat/<uuid:conversation_id>/action/', chat_conversation_action_view, name='chat_conversation_action'),
    path('chat/website/settings/', website_chat_settings_view, name='website_chat_settings'),
    path('chat/widget/<uuid:public_key>/', website_chat_widget_view, name='website_chat_widget'),
    path('chat/widget/<uuid:public_key>/launcher.js', website_chat_launcher_view, name='website_chat_launcher'),
    path('workforce/activity/', work_activity_ledger_view, name='work_activity_ledger'),
    path('workforce/team/<int:member_id>/', team_member_detail_view, name='team_member_detail'),
    path('workforce/photos/<int:worker_id>/', employee_photo_view, name='employee_photo'),
    path('workforce/documents/<int:document_id>/download/', employee_document_download_view, name='employee_document_download'),
    path('reports/', reports_view, name='reports'),
    path('settings/', admin_console_view, name='admin_console'),
    path('workspaces/new/', create_workspace_view, name='workspace_create'),
    path('billing/', billing_overview_view, name='billing_overview'),
    path('billing/checkout/', create_checkout_session_view, name='billing_checkout'),
    path('billing/portal/', create_billing_portal_view, name='billing_portal'),
    path('billing/webhook/stripe/', stripe_webhook_view, name='stripe_webhook'),
    path('me/', employee_profile_view, name='employee_profile'),
    path('field/', field_operations_view, name='field_operations'),
    path('field/jobs/<int:job_id>/', field_job_view, name='field_job'),
    
    # FIX: Added Django's built-in authentication URLs
    path('accounts/', include('django.contrib.auth.urls')), 
    
    # --- UNIFIED REST API ---
    path('api/v1/', include(router.urls)),
    path('api/address/postal-code/', postal_code_lookup_view, name='postal_code_lookup'),
    
    # --- INTERNAL MAP DASHBOARD API ---
    path('api/fleet/live-locations/', LiveFleetLocationsView.as_view(), name='api_live_fleet'),
    
    # --- MOBILE APP ENDPOINTS ---
    path('api/mobile/upload-evidence/', EvidenceUploadView.as_view(), name='api_upload_evidence'),
    path('api/mobile/jobs/<int:job_id>/clock-in/', MobileClockInView.as_view(), name='api_mobile_clock_in'),
    path('api/mobile/jobs/<int:job_id>/clock-out/', MobileClockOutView.as_view(), name='api_mobile_clock_out'),
    path('api/mobile/track-location/', TrackLocationPingView.as_view(), name='api_track_location'),
    path('api/mobile/shift/', FieldShiftView.as_view(), name='api_field_shift'),
    path('api/mobile/jobs/<int:job_id>/action/', FieldJobActionView.as_view(), name='api_field_job_action'),
    path('api/mobile/jobs/<int:job_id>/activity/', FieldWorkActivityView.as_view(), name='api_field_work_activity'),
    path('api/mobile/jobs/<int:job_id>/report-problem/', FieldIssueReportView.as_view(), name='api_field_report_problem'),
    path('api/field-issues/<int:issue_id>/status/', FieldIssueStatusView.as_view(), name='api_field_issue_status'),
    path('api/calendar/options/', calendar_options_view, name='api_calendar_options'),
    path('api/calendar/jobs/', calendar_jobs_view, name='api_calendar_jobs'),
    path('api/calendar/jobs/<int:job_id>/', calendar_job_update_view, name='api_calendar_job_update'),
    path('api/passkeys/register/options/', passkey_registration_options, name='passkey_register_options'),
    path('api/passkeys/register/verify/', passkey_registration_verify, name='passkey_register_verify'),
    path('api/passkeys/login/options/', passkey_authentication_options, name='passkey_login_options'),
    path('api/passkeys/login/verify/', passkey_authentication_verify, name='passkey_login_verify'),
]
