# c:\Users\navee\Music\VebGen\vebgen sharp\backend\src\core\test_code_intelligence.py

import json
import pytest
import logging
from pathlib import Path


# We are testing the service, so we import it and its constants directly.
from src.core.code_intelligence_service import CodeIntelligenceService, MAX_FILE_SIZE_BYTES, MAX_LINE_COUNT
# --- NEW: Import performance monitor for testing ---
from src.core.performance_monitor import performance_monitor

# Configure basic logging to see the output from the service during the test.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# --- Test Data: Sample Code Strings ---

# Sample models.py content
SAMPLE_MODELS_PY = """
from django.db import models
from django.contrib.auth.models import User

class Question(models.Model):
    # This is a sample model field.
    question_text = models.CharField(max_length=200, help_text="The text of the question.")
    pub_date = models.DateTimeField('date published')
    author = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return self.question_text

    class Meta:
        ordering = ['-pub_date']
        verbose_name = "Poll Question"
"""

# Sample views.py content with both Function-Based and Class-Based Views
SAMPLE_VIEWS_PY = """
from django.shortcuts import render, redirect
from django.views.generic import ListView
from .models import Question, Choice
from .forms import QuestionForm

# This is a function-based view.
def detail(request, question_id):
    question = Question.objects.get(pk=question_id)
    return render(request, 'polls/detail.html', {'question': question})

# This is a class-based view.
class QuestionListView(ListView):
    model = Question
    template_name = 'polls/index.html'
    context_object_name = 'latest_question_list'

    def get_queryset(self):
        \"\"\"Return the last five published questions.\"\"\"
        return Question.objects.order_by('-pub_date')[:5]

def vote(request, question_id):
    # some logic
    return redirect('polls:results', question_id=question.id)
"""

# Sample urls.py content
SAMPLE_URLS_PY = """
from django.urls import path, include
from . import views

app_name = 'polls'
urlpatterns = [
    path('', views.QuestionListView.as_view(), name='index'),
    path('<int:question_id>/', views.detail, name='detail'),
    path('api/', include('polls.api.urls')),
]
"""

# Sample forms.py content
SAMPLE_FORMS_PY = """
from django import forms
from .models import Question

class QuestionForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = ['question_text', 'author']
"""

# Sample complex models.py content for stress testing
SAMPLE_COMPLEX_MODELS_PY = """
from django.db import models
from django.utils import timezone

class ArticleManager(models.Manager):
    def published(self):
        return self.get_queryset().filter(status='published')

class Tag(models.Model):
    name = models.CharField(max_length=100, unique=True)

class Article(models.Model):
    title = models.CharField(max_length=250)
    tags = models.ManyToManyField(
        Tag,
        through='TaggedArticle',
        related_name='articles'
    )
    objects = ArticleManager() # Custom manager

    @property
    def word_count(self):
        return len(self.content.split())

class TaggedArticle(models.Model):
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)
    article = models.ForeignKey(Article, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('tag', 'article')
"""

# Sample admin.py for advanced parsing test
SAMPLE_ADMIN_PY = """
from django.contrib import admin
from .models import Question, Article

# Simple registration
admin.site.register(Question)

# Registration with a ModelAdmin class using a decorator
@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'created_at')
    search_fields = ['title', 'content']
"""

# --- Test Data for Aliased Imports ---
SAMPLE_ALIASED_MODELS_PY = """
from django.db import models as db_models

class Product(db_models.Model):
    name = db_models.CharField(max_length=100)
    price = db_models.DecimalField(max_digits=10, decimal_places=2)
"""

SAMPLE_ALIASED_ADMIN_PY = """
from django.contrib import admin as dj_admin
from .models import Product

@dj_admin.register(Product)
class ProductAdmin(dj_admin.ModelAdmin):
    list_display = ('name', 'price')
"""

# --- NEW: Test Data for Views, Serializers, TemplateTags ---

SAMPLE_DRF_VIEWS_PY = """
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from .models import Question
from .serializers import QuestionSerializer

class QuestionViewSet(ModelViewSet):
    queryset = Question.objects.all()
    serializer_class = QuestionSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = 'rest_framework.pagination.PageNumberPagination'
"""

SAMPLE_SERIALIZERS_PY = """
from rest_framework import serializers
from .models import Question, Choice

class ChoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Choice
        fields = ['id', 'choice_text', 'votes']

class QuestionSerializer(serializers.ModelSerializer):
    choices = ChoiceSerializer(many=True, read_only=True)
    author_name = serializers.CharField(source='author.username', read_only=True)

    class Meta:
        model = Question
        fields = ['id', 'question_text', 'pub_date', 'author_name', 'choices']
"""

SAMPLE_TEMPLATETAGS_PY = """
from django import template

register = template.Library()

@register.simple_tag(name='show_custom_results')
def show_results(question):
    return f"Results for {question.question_text}"
"""

# --- NEW: Test Data for Signals, Celery, Channels, Advanced Tests ---

SAMPLE_SIGNALS_PY = """
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import UserProfile

@receiver(post_save, sender=UserProfile)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        print(f"New profile created for user {instance.user.username}")
"""

SAMPLE_SIGNALS_WITH_UID_PY = """
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import UserProfile

@receiver(post_save, sender=UserProfile, dispatch_uid="my_unique_profile_creation_signal")
def create_user_profile_with_uid(sender, instance, created, **kwargs):
    if created:
        print(f"New profile created for user {instance.user.username}")
"""

SAMPLE_CELERY_TASKS_PY = """
from celery import shared_task

@shared_task(bind=True, max_retries=3)
def send_welcome_email(self, user_id):
    # Logic to send an email
    print(f"Sending email to user {user_id}")
"""

SAMPLE_CELERY_TASKS_WITH_RETRY_PY = """
from celery import shared_task

@shared_task(bind=True, max_retries=3)
def send_flaky_email(self, user_id):
    try:
        # some flaky operation
        print(f"Attempting to send email to user {user_id}")
    except Exception as exc:
        self.retry(exc=exc, countdown=60)
"""

SAMPLE_CHANNELS_CONSUMERS_PY = """
import json
from channels.generic.websocket import AsyncWebsocketConsumer

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()

    async def disconnect(self, close_code):
        pass

    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message = text_data_json['message']
        await self.send(text_data=json.dumps({'message': message}))
"""

SAMPLE_ADVANCED_TESTS_PY = """
from django.test import TestCase, RequestFactory
from rest_framework.test import APITestCase
from .models import Question

class QuestionAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        Question.objects.create(question_text="Initial question for API test.", pub_date=timezone.now())

    def test_list_questions_api(self):
        response = self.client.get('/api/questions/')
        self.assertEqual(response.status_code, 200)
"""

# Sample views.py with advanced ORM queries
SAMPLE_ORM_VIEWS_PY = """
from django.shortcuts import render
from django.db.models import Count
from .models import Question, Choice

def advanced_query_view(request):
    # Using select_related, prefetch_related, and annotate
    questions = Question.objects.select_related('author').prefetch_related('choice_set').annotate(
        choice_count=Count('choice')
    )

    # Using raw SQL
    raw_questions = Question.objects.raw("SELECT * FROM polls_question")

    # Using aggregate
    total_questions = Question.objects.aggregate(total=Count('id'))

    return render(request, 'polls/advanced.html', {'questions': questions})
"""

# --- NEW: Test Data for Advanced Django Parsing ---

# Sample settings.py for advanced parsing
SAMPLE_SETTINGS_PY = """
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-default-key')
DEBUG = True

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'polls.apps.PollsConfig',
    'rest_framework',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'polls.middleware.performance.PerformanceMonitoringMiddleware',
]

ROOT_URLCONF = 'myproject.urls'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'myproject.auth.CustomBackend',
]

LANGUAGE_CODE = 'en-us'
USE_I18N = True
LOCALE_PATHS = [BASE_DIR / 'locale']
"""

SAMPLE_SETTINGS_WITH_CELERY_BEAT_PY = """
from celery.schedules import crontab

INSTALLED_APPS = ['django_celery_beat']

CELERY_BEAT_SCHEDULE = {
    'send-summary-every-hour': {
        'task': 'myapp.tasks.send_summary',
        'schedule': crontab(minute=0, hour='*/1'),
    },
}
"""

SAMPLE_MODEL_WITH_CHANNEL_SEND_PY = """
from django.db import models
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
class Notification(models.Model):
    message = models.CharField(max_length=255)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)('notifications', {'type': 'send_notification', 'message': self.message})
"""

# Sample urls.py with DRF router
SAMPLE_URLS_WITH_DRF_ROUTER_PY = """
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'questions', views.QuestionViewSet, basename='question')

urlpatterns = [
    path('', include(router.urls)),
]
"""
def test_code_intelligence_parsing(capsys):
    """
    This test function validates the CodeIntelligenceService by feeding it
    predefined code strings and asserting that the output is valid JSON.
    """
    print("--- Starting Code Intelligence Service Test ---")

    # We need a dummy project root. A temporary directory or '.' works fine.
    # The service uses this to resolve paths, but for this test, we are
    # passing content directly, so the path is mostly for context.
    dummy_project_root = Path.cwd() / "test_project_temp"
    dummy_project_root.mkdir(exist_ok=True)
    print(f"Using dummy project root: {dummy_project_root}\n")

    # Instantiate the service we want to test.
    intelligence_service = CodeIntelligenceService(project_root=dummy_project_root)

    # --- Test Case 1: Django Models File ---
    print("\n--- 1. Testing models.py Parsing ---")
    models_info = intelligence_service.parse_file("polls/models.py", SAMPLE_MODELS_PY)

    assert models_info is not None, "Parsing models.py should return a valid object."
    assert models_info.file_type == "django_model"
    assert models_info.django_model_details is not None

    # Convert to dict for easier assertions
    models_data = models_info.django_model_details.model_dump()

    assert len(models_data["models"]) == 1, "Should find exactly one model."
    question_model = models_data["models"][0]
    assert question_model["name"] == "Question"
    assert "models.Model" in question_model["bases"]

    # Assert specific fields are parsed correctly
    fields = {f["name"]: f for f in question_model["django_fields"]}
    assert "question_text" in fields
    assert fields["question_text"]["field_type"] == "CharField"
    assert fields["question_text"]["args"]["max_length"] == 200
    assert fields["author"]["field_type"] == "ForeignKey"
    assert fields["author"]["related_model_name"] == "User"
    assert fields["author"]["on_delete"] == "models.CASCADE"
    assert question_model["meta_options"]["verbose_name"] == "Poll Question"
    print("✅ models.py assertions passed.")

    # --- Test Case 6: Complex Admin File ---
    print("\n--- 6. Testing Complex admin.py Parsing (@register decorator) ---")
    admin_info = intelligence_service.parse_file("polls/admin.py", SAMPLE_ADMIN_PY)
    assert admin_info is not None, "Parsing admin.py should return a valid object."
    assert admin_info.file_type == "django_admin"
    assert admin_info.django_admin_details is not None

    admin_data = admin_info.django_admin_details.model_dump()

    assert len(admin_data["registered_models"]) == 2, "Should find two registered models."
    
    # Find the registration for the 'Article' model
    article_reg = next((r for r in admin_data["registered_models"] if r["model"] == "Article"), None)
    assert article_reg is not None, "Article model registration should be found."
    assert article_reg["admin_class"] == "ArticleAdmin", "Should associate Article with ArticleAdmin class via decorator."

    # Find the parsed ArticleAdmin class and check its attributes
    article_admin_class = next((c for c in admin_data["admin_classes"] if c["name"] == "ArticleAdmin"), None)
    assert article_admin_class is not None, "ArticleAdmin class should be parsed."
    assert "list_display" in [attr["name"] for attr in article_admin_class["attributes"]]
    print("✅ complex_admin.py assertions passed.")

    # --- Test Case 7: Aliased Imports ---
    print("\n--- 7. Testing Aliased Import Parsing ---")
    # This test ensures the service can handle `from ... import ... as ...`
    aliased_models_info = intelligence_service.parse_file("shop/models.py", SAMPLE_ALIASED_MODELS_PY)
    assert aliased_models_info is not None, "Parsing aliased models.py should return a valid object."
    assert aliased_models_info.file_type == "django_model"
    assert aliased_models_info.django_model_details is not None

    aliased_models_data = aliased_models_info.django_model_details.model_dump()
    assert len(aliased_models_data["models"]) == 1, "Should find one model with aliased import."
    product_model = aliased_models_data["models"][0]
    assert product_model["name"] == "Product"
    assert any("db_models.Model" in base for base in product_model["bases"]), "Should correctly identify base class with alias."
    assert len(product_model["django_fields"]) == 2, "Should parse fields defined with aliased models."

    aliased_admin_info = intelligence_service.parse_file("shop/admin.py", SAMPLE_ALIASED_ADMIN_PY)
    assert aliased_admin_info is not None, "Parsing aliased admin.py should return a valid object."
    assert aliased_admin_info.file_type == "django_admin"
    assert aliased_admin_info.django_admin_details is not None
    aliased_admin_data = aliased_admin_info.django_admin_details.model_dump()
    assert len(aliased_admin_data["registered_models"]) == 1, "Should find one registered model with aliased admin decorator."
    assert aliased_admin_data["registered_models"][0]["model"] == "Product"
    print("✅ aliased_imports.py assertions passed.")

def test_parse_drf_viewset(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a DRF ViewSet with permissions and pagination."""
    print("\n--- Testing DRF ViewSet Parsing ---")
    view_info = intelligence_service.parse_file("polls/views.py", SAMPLE_DRF_VIEWS_PY)
    assert view_info is not None
    assert view_info.file_type == "django_view"
    assert view_info.django_view_details is not None

    viewsets = view_info.django_view_details.drf_viewsets
    assert len(viewsets) == 1
    
    vs = viewsets[0]
    assert vs.name == "QuestionViewSet"
    assert vs.serializer_class == "QuestionSerializer"
    assert "IsAuthenticated" in vs.permission_classes
    assert vs.pagination_class == "'rest_framework.pagination.PageNumberPagination'"
    print("✅ DRF ViewSet parsing assertions passed.")

def test_parse_drf_serializer(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a DRF serializer file."""
    print("\n--- Testing DRF Serializer Parsing ---")
    serializer_info = intelligence_service.parse_file("polls/serializers.py", SAMPLE_SERIALIZERS_PY)
    assert serializer_info is not None
    assert serializer_info.file_type == "django_serializer"
    assert serializer_info.django_serializer_details is not None

    serializers = serializer_info.django_serializer_details.serializers
    assert len(serializers) == 2

    q_serializer = next((s for s in serializers if s.name == "QuestionSerializer"), None)
    assert q_serializer is not None
    assert q_serializer.meta_model == "Question"
    assert "author_name" in [f.name for f in q_serializer.serializer_fields]
    
    author_name_field = next(f for f in q_serializer.serializer_fields if f.name == "author_name")
    assert author_name_field.source == "author.username"
    assert author_name_field.read_only is True
    print("✅ DRF Serializer parsing assertions passed.")

def test_parse_templatetags(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a custom templatetags file."""
    print("\n--- Testing TemplateTag Parsing ---")
    # Create a dummy directory structure for the test
    (intelligence_service.project_root / "polls" / "templatetags").mkdir(parents=True, exist_ok=True)
    
    tag_info = intelligence_service.parse_file("polls/templatetags/poll_extras.py", SAMPLE_TEMPLATETAGS_PY)
    assert tag_info is not None
    assert tag_info.file_type == "django_templatetag"
    assert tag_info.django_templatetag_details is not None

    tags = tag_info.django_templatetag_details.tags_and_filters
    assert len(tags) == 1
    tag = tags[0]
    assert tag.name == "show_custom_results"
    assert tag.tag_type == "simple_tag"
    print("✅ TemplateTag parsing assertions passed.")

def test_parse_signal_file(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a signals.py file."""
    print("\n--- Testing Signal Parsing ---")
    signal_info = intelligence_service.parse_file("polls/signals.py", SAMPLE_SIGNALS_PY)
    assert signal_info is not None
    assert signal_info.file_type == "django_signal"
    assert signal_info.django_signal_details is not None

    receivers = signal_info.django_signal_details.receivers
    assert len(receivers) == 1
    receiver = receivers[0]
    assert receiver.name == "create_user_profile"
    assert receiver.signal == "post_save"
    assert receiver.sender == "UserProfile"
    print("✅ Signal parsing assertions passed.")

def test_parse_signal_file_with_dispatch_uid(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a signals.py file with a dispatch_uid."""
    print("\n--- Testing Signal Parsing with dispatch_uid ---")
    signal_info = intelligence_service.parse_file("polls/signals_uid.py", SAMPLE_SIGNALS_WITH_UID_PY)
    assert signal_info is not None
    assert signal_info.file_type == "django_signal"
    assert signal_info.django_signal_details is not None

    receivers = signal_info.django_signal_details.receivers
    assert len(receivers) == 1
    receiver = receivers[0]
    assert receiver.name == "create_user_profile_with_uid"
    assert receiver.dispatch_uid == "my_unique_profile_creation_signal"
    print("✅ Signal parsing with dispatch_uid assertions passed.")

def test_parse_celery_task_file(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a Celery tasks.py file."""
    print("\n--- Testing Celery Task Parsing ---")
    task_info = intelligence_service.parse_file("polls/tasks.py", SAMPLE_CELERY_TASKS_PY)
    assert task_info is not None
    assert task_info.file_type == "celery_task"
    assert task_info.celery_task_details is not None

    tasks = task_info.celery_task_details.tasks
    assert len(tasks) == 1
    task = tasks[0]
    assert task.name == "send_welcome_email"
    assert task.task_options.get("bind") == "True"
    assert task.task_options.get("max_retries") == "3"
    print("✅ Celery task parsing assertions passed.")

def test_parse_celery_task_with_retry(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a Celery task that uses self.retry()."""
    print("\n--- Testing Celery Task with Retry Parsing ---")
    task_info = intelligence_service.parse_file("polls/tasks_retry.py", SAMPLE_CELERY_TASKS_WITH_RETRY_PY)
    assert task_info is not None
    assert task_info.file_type == "celery_task"
    assert task_info.celery_task_details is not None

    tasks = task_info.celery_task_details.tasks
    assert len(tasks) == 1
    task = tasks[0]
    assert task.uses_retry is True, "Should detect the self.retry() call in the task body."
    print("✅ Celery task with retry parsing assertions passed.")

def test_parse_channels_consumer_file(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a Django Channels consumers.py file."""
    print("\n--- Testing Channels Consumer Parsing ---")
    consumer_info = intelligence_service.parse_file("chat/consumers.py", SAMPLE_CHANNELS_CONSUMERS_PY)
    assert consumer_info is not None
    assert consumer_info.file_type == "django_channels_consumer"
    assert consumer_info.django_channels_consumer_details is not None
    consumers = consumer_info.django_channels_consumer_details.consumers
    assert len(consumers) == 1
    consumer = consumers[0]
    assert consumer.name == "ChatConsumer"
    assert "AsyncWebsocketConsumer" in consumer.bases
    method_names = {m.name for m in consumer.methods}
    assert "connect" in method_names
    assert "disconnect" in method_names
    assert "receive" in method_names
    print("✅ Channels consumer parsing assertions passed.")

def test_parse_advanced_tests_file(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a tests.py file with advanced patterns like setUpTestData and APIClient."""
    print("\n--- Testing Advanced Test File Parsing ---")
    test_info = intelligence_service.parse_file("polls/tests.py", SAMPLE_ADVANCED_TESTS_PY)
    assert test_info is not None
    assert test_info.file_type == "django_test"
    assert test_info.django_test_details is not None

    test_classes = test_info.django_test_details.test_classes
    assert len(test_classes) == 1
    test_class = test_classes[0]
    assert test_class.name == "QuestionAPITests"
    assert test_class.has_setup_test_data is True
    assert test_class.uses_api_client is True
    print("✅ Advanced test file parsing assertions passed.")

def test_parse_settings_py_advanced(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a settings.py file with various configurations."""
    print("\n--- Testing settings.py Advanced Parsing ---")
    # The app name 'myproject' is hardcoded in the settings content, so we use it here.
    # The service checks if the app name from the path matches the project root name.
    # We need to simulate this structure.
    project_root_name = "myproject"
    intelligence_service.project_root = intelligence_service.project_root.parent / project_root_name
    intelligence_service.project_root.mkdir(exist_ok=True)

    settings_info = intelligence_service.parse_file(f"{project_root_name}/settings.py", SAMPLE_SETTINGS_PY)

    assert settings_info is not None
    assert settings_info.file_type == "django_settings"
    assert settings_info.django_settings_details is not None

    key_settings = settings_info.django_settings_details.key_settings
    assert "INSTALLED_APPS" in key_settings
    assert "polls.apps.PollsConfig" in key_settings["INSTALLED_APPS"]
    assert "MIDDLEWARE" in key_settings
    assert "polls.middleware.performance.PerformanceMonitoringMiddleware" in key_settings["MIDDLEWARE"]
    assert "AUTHENTICATION_BACKENDS" in key_settings
    assert "myproject.auth.CustomBackend" in key_settings["AUTHENTICATION_BACKENDS"]
    assert key_settings.get("LANGUAGE_CODE") == "en-us"
    assert key_settings.get("SECRET_KEY") == "os.environ.get('SECRET_KEY', 'django-insecure-default-key')"
    assert "SECRET_KEY" in settings_info.django_settings_details.env_vars_used
    assert settings_info.django_settings_details.env_vars_used["SECRET_KEY"] == "SECRET_KEY"
    print("✅ settings.py advanced parsing assertions passed.")

def test_parse_settings_with_celery_beat(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a settings.py file with a CELERY_BEAT_SCHEDULE."""
    print("\n--- Testing settings.py with Celery Beat Parsing ---")
    project_root_name = "myproject"
    intelligence_service.project_root = intelligence_service.project_root.parent / project_root_name
    intelligence_service.project_root.mkdir(exist_ok=True)

    settings_info = intelligence_service.parse_file(f"{project_root_name}/settings.py", SAMPLE_SETTINGS_WITH_CELERY_BEAT_PY)
    assert settings_info is not None
    assert settings_info.file_type == "django_settings"
    assert settings_info.django_settings_details is not None

    schedules = settings_info.django_settings_details.celery_beat_schedules
    assert len(schedules) == 1
    assert schedules[0].task_name == "myapp.tasks.send_summary"
    assert "crontab" in schedules[0].schedule
    print("✅ settings.py with Celery Beat parsing assertions passed.")

def test_parse_settings_py_dynamic_apps(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a settings.py file with dynamically modified INSTALLED_APPS."""
    print("\n--- Testing settings.py Dynamic INSTALLED_APPS Parsing ---")
    
    dynamic_settings_content = """
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
]

if DEBUG:
    INSTALLED_APPS += ('debug_toolbar',)

INSTALLED_APPS.append('corsheaders')
    """
    
    # The service checks if the app name from the path matches the project root name.
    # We need to simulate this structure.
    project_root_name = "myproject"
    intelligence_service.project_root = intelligence_service.project_root.parent / project_root_name
    intelligence_service.project_root.mkdir(exist_ok=True)

    settings_info = intelligence_service.parse_file(f"{project_root_name}/settings_dev.py", dynamic_settings_content)

    assert settings_info is not None
    assert settings_info.file_type == "django_settings"
    assert settings_info.django_settings_details is not None

    key_settings = settings_info.django_settings_details.key_settings
    assert "INSTALLED_APPS" in key_settings
    installed_apps = key_settings["INSTALLED_APPS"]
    assert 'django.contrib.admin' in installed_apps
    assert 'debug_toolbar' in installed_apps
    assert 'corsheaders' in installed_apps
    assert len(installed_apps) == 4
    print("✅ settings.py dynamic INSTALLED_APPS parsing assertions passed.")

def test_parse_orm_query_intelligence(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a views.py file with advanced ORM queries."""
    print("\n--- Testing ORM Query Intelligence Parsing ---")
    view_info = intelligence_service.parse_file("polls/views.py", SAMPLE_ORM_VIEWS_PY)

    assert view_info is not None
    assert view_info.file_type == "django_view"
    assert view_info.django_view_details is not None

    views = view_info.django_view_details.views
    assert len(views) == 1, "Should find one view function."
    
    view = views[0]
    assert view.name == "advanced_query_view"
    
    # Check for select_related and prefetch_related
    assert "select_related" in view.queryset_optimizations
    assert "prefetch_related" in view.queryset_optimizations
    
    # Check for raw SQL usage
    assert view.uses_raw_sql is True, "Should detect usage of .raw()"
    
    # Check for annotations and aggregations
    assert "choice_count" in view.aggregations_annotations, "Should detect 'annotate' keyword argument."
    assert "total" in view.aggregations_annotations, "Should detect 'aggregate' keyword argument."

    print("✅ ORM Query Intelligence parsing assertions passed.")

def test_parse_channel_layer_invocation(intelligence_service: CodeIntelligenceService):
    """Tests detection of channel_layer.group_send in a model's save method."""
    print("\n--- Testing Channel Layer Invocation Parsing ---")
    model_info = intelligence_service.parse_file("notifications/models.py", SAMPLE_MODEL_WITH_CHANNEL_SEND_PY)
    assert model_info is not None
    assert model_info.file_type == "django_model"
    assert model_info.django_model_details is not None

    notification_model = model_info.django_model_details.models[0]
    save_method = next((m for m in notification_model.methods if m.name == "save"), None)
    assert save_method is not None
    assert len(save_method.channel_layer_invocations) == 1
    assert "channel_layer.group_send" in save_method.channel_layer_invocations[0]
    print("✅ Channel layer invocation parsing assertions passed.")

def test_parse_migration_file(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a Django migration file."""
    # Sample migration file
    SAMPLE_MIGRATION_FILE_PY = """
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('polls', '0001_initial')]
    operations = [migrations.AddField(model_name='question', name='was_published_recently', field=models.BooleanField(default=False))]

"""

    print("\n--- Testing Django Migration File Parsing ---")
    migration_info = intelligence_service.parse_file("polls/migrations/0002_auto.py", SAMPLE_MIGRATION_FILE_PY)

    assert migration_info is not None
    assert migration_info.file_type == "django_migration"
    assert migration_info.django_migration_details is not None

    details = migration_info.django_migration_details
    assert len(details.dependencies) == 1, "Should find one dependency."
    assert details.dependencies[0] == ("polls", "0001_initial")

    assert len(details.operations) == 1, "Should find one operation."
    assert details.operations[0].type == "AddField"
    print("✅ Django migration file assertions passed.")

@pytest.fixture
def intelligence_service(tmp_path: Path) -> CodeIntelligenceService:
    """Provides a CodeIntelligenceService instance for tests."""
    return CodeIntelligenceService(project_root=tmp_path)


def test_parse_models_py(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a standard models.py file."""
    print("\n--- Testing models.py Parsing ---")
    models_info = intelligence_service.parse_file("polls/models.py", SAMPLE_MODELS_PY)

    assert models_info is not None, "Parsing models.py should return a valid object."
    assert models_info.file_type == "django_model"
    assert models_info.django_model_details is not None

    models_data = models_info.django_model_details.model_dump()

    assert len(models_data["models"]) == 1, "Should find exactly one model."
    question_model = models_data["models"][0]
    assert question_model["name"] == "Question"
    assert "models.Model" in question_model["bases"]

    fields = {f["name"]: f for f in question_model["django_fields"]}
    assert "question_text" in fields
    assert fields["question_text"]["field_type"] == "CharField"
    assert fields["question_text"]["args"]["max_length"] == 200
    assert fields["author"]["field_type"] == "ForeignKey"
    assert fields["author"]["related_model_name"] == "User"
    assert fields["author"]["on_delete"] == "models.CASCADE"
    assert question_model["meta_options"]["verbose_name"] == "Poll Question"
    print("✅ models.py assertions passed.")


def test_parse_views_py(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a standard views.py file with FBVs and CBVs."""
    print("\n--- Testing views.py Parsing (FBV and CBV) ---")
    views_info = intelligence_service.parse_file("polls/views.py", SAMPLE_VIEWS_PY)
    assert views_info is not None, "Parsing views.py should return a valid object."
    assert views_info.file_type == "django_view"
    assert views_info.django_view_details is not None

    views_data = views_info.django_view_details.model_dump()
    view_names = {v["name"] for v in views_data["views"]}
    assert "detail" in view_names, "Function-based view 'detail' should be parsed."
    assert "QuestionListView" in view_names, "Class-based view 'QuestionListView' should be parsed."

    # Assert details of a specific view
    detail_view = next((v for v in views_data["views"] if v["name"] == "detail"), None)
    assert detail_view is not None
    assert "polls/detail.html" in detail_view["rendered_templates"]
    assert "Question" in detail_view["models_queried"]
    print("✅ views.py assertions passed.")


def test_parse_admin_py(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a standard admin.py file."""
    print("\n--- Testing admin.py Parsing (@register decorator) ---")
    admin_info = intelligence_service.parse_file("polls/admin.py", SAMPLE_ADMIN_PY)
    assert admin_info is not None, "Parsing admin.py should return a valid object."
    assert admin_info.file_type == "django_admin"
    assert admin_info.django_admin_details is not None

    admin_data = admin_info.django_admin_details.model_dump()

    assert len(admin_data["registered_models"]) == 2, "Should find two registered models."

    # Find the registration for the 'Article' model
    article_reg = next((r for r in admin_data["registered_models"] if r["model"] == "Article"), None)
    assert article_reg is not None, "Article model registration should be found."
    assert article_reg["admin_class"] == "ArticleAdmin", "Should associate Article with ArticleAdmin class via decorator."

    # Find the parsed ArticleAdmin class and check its attributes
    article_admin_class = next((c for c in admin_data["admin_classes"] if c["name"] == "ArticleAdmin"), None)
    assert article_admin_class is not None, "ArticleAdmin class should be parsed."
    assert "list_display" in [attr["name"] for attr in article_admin_class["attributes"]]
    print("✅ admin.py assertions passed.")


def test_parse_urls_py(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a standard urls.py file."""
    print("\n--- Testing urls.py Parsing ---")
    urls_info = intelligence_service.parse_file("polls/urls.py", SAMPLE_URLS_PY)
    assert urls_info is not None, "Parsing urls.py should return a valid object."
    assert urls_info.file_type == "django_urls"
    assert urls_info.django_urls_details is not None

    urls_data = urls_info.django_urls_details.model_dump()
    assert urls_data["app_name"] == "polls"
    assert len(urls_data["url_patterns"]) == 2, "Should find two url patterns."
    assert len(urls_data["includes"]) == 1, "Should find one include."

    # Assert details of a specific pattern
    detail_pattern = next((p for p in urls_data["url_patterns"] if p["name"] == "detail"), None)
    assert detail_pattern is not None
    assert detail_pattern["pattern"] == "<int:question_id>/"
    assert detail_pattern["view_reference"] == "views.detail"
    print("✅ urls.py assertions passed.")


def test_parse_forms_py(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a standard forms.py file."""
    print("\n--- Testing forms.py Parsing (ModelForm) ---")
    forms_info = intelligence_service.parse_file("polls/forms.py", SAMPLE_FORMS_PY)
    assert forms_info is not None, "Parsing forms.py should return a valid object."
    assert forms_info.file_type == "django_form"
    assert forms_info.django_form_details is not None

    forms_data = forms_info.django_form_details.model_dump()
    assert len(forms_data["forms"]) == 1, "Should find exactly one form."

    question_form = forms_data["forms"][0]
    assert question_form["name"] == "QuestionForm"
    assert "forms.ModelForm" in question_form["bases"]
    assert question_form["meta_model"] == "Question"
    assert "question_text" in question_form["meta_fields"]
    assert "author" in question_form["meta_fields"]
    print("✅ forms.py assertions passed.")


def test_parse_complex_models_py(intelligence_service: CodeIntelligenceService):
    """Tests parsing of a complex models.py file with M2M fields and custom managers."""
    print("\n--- Testing Complex models.py Parsing (M2M through, custom manager) ---")
    complex_models_info = intelligence_service.parse_file("polls/complex_models.py", SAMPLE_COMPLEX_MODELS_PY)
    assert complex_models_info is not None, "Parsing complex models.py should return a valid object."
    assert complex_models_info.file_type == "django_model"
    assert complex_models_info.django_model_details is not None

    complex_data = complex_models_info.django_model_details.model_dump()

    assert len(complex_data["models"]) == 3, "Should find exactly three models: Article, Tag, TaggedArticle."

    article_model = next((m for m in complex_data["models"] if m["name"] == "Article"), None)
    assert article_model is not None, "Article model should be parsed."

    # Assert ManyToManyField with 'through' model is parsed
    m2m_field = next((f for f in article_model["django_fields"] if f["name"] == "tags"), None)
    assert m2m_field is not None, "tags ManyToManyField should be parsed."
    assert m2m_field["field_type"] == "ManyToManyField"
    assert m2m_field["args"]["through"] == "TaggedArticle", "The 'through' argument of the M2M field should be correctly parsed."

    # Assert custom manager is identified as an attribute
    custom_manager_attr = next((attr for attr in article_model["attributes"] if attr["name"] == "objects"), None)
    assert custom_manager_attr is not None, "Custom manager 'objects' should be identified as a class attribute."
    assert custom_manager_attr["value_preview"] == "ArticleManager()"
    print("✅ complex_models.py assertions passed.")


def test_crash_prevention_parsing(tmp_path: Path):
    """
    Tests the crash prevention mechanisms in CodeIntelligenceService,
    including binary file detection and file size/line limits.
    """
    print("\n--- Starting Crash Prevention Parsing Test ---")

    # Instantiate the service with the temporary directory
    intelligence_service = CodeIntelligenceService(project_root=tmp_path)

    # --- Test Case 1: Binary file detection by extension ---
    print("\n--- 1. Testing binary file detection (by extension) ---")
    binary_file_by_ext = tmp_path / "logo.png"
    binary_file_by_ext.write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR...') # Dummy PNG header

    # We pass the content as a string, simulating how it would be read with errors='ignore'
    binary_content_as_str = binary_file_by_ext.read_text(encoding='utf-8', errors='ignore')
    result_ext = intelligence_service.parse_file(str(binary_file_by_ext.relative_to(tmp_path)), binary_content_as_str)

    assert result_ext is not None
    assert result_ext.file_type == "unknown"
    assert "Skipped: File has a binary extension" in result_ext.raw_content_summary
    print("✅ Binary file (by extension) was correctly skipped.")

    # --- Test Case 2: Binary file detection by content heuristic (null bytes) ---
    print("\n--- 2. Testing binary file detection (by content) ---")
    binary_file_by_content = tmp_path / "data.bin" # Non-binary extension
    binary_file_by_content.write_bytes(b'some text\x00with a null byte')

    binary_content_with_null = binary_file_by_content.read_text(encoding='utf-8', errors='ignore')
    result_content = intelligence_service.parse_file(str(binary_file_by_content.relative_to(tmp_path)), binary_content_with_null)

    assert result_content is not None
    assert result_content.file_type == "unknown"
    assert "Skipped: File content contains null bytes" in result_content.raw_content_summary
    print("✅ Binary file (by content) was correctly skipped.")

    # --- Test Case 3: File size protection ---
    print("\n--- 3. Testing file size protection ---")
    large_file = tmp_path / "large_file.txt"
    # Create content slightly larger than the max allowed size
    large_content = "a" * (MAX_FILE_SIZE_BYTES + 100)
    large_file.write_text(large_content)

    result_size = intelligence_service.parse_file(str(large_file.relative_to(tmp_path)), large_content)

    assert result_size is not None
    assert result_size.file_type == "unknown"
    assert "Skipped: File size" in result_size.raw_content_summary
    assert "exceeds maximum" in result_size.raw_content_summary
    print("✅ Oversized file was correctly skipped.")

    # --- Test Case 4: Line count protection ---
    print("\n--- 4. Testing line count protection ---")
    long_file = tmp_path / "long_file.txt"
    # Create content with more lines than the max allowed count
    long_content = "\n" * (MAX_LINE_COUNT + 5)
    long_file.write_text(long_content)

    result_lines = intelligence_service.parse_file(str(long_file.relative_to(tmp_path)), long_content)

    assert result_lines is not None
    assert result_lines.file_type == "unknown"
    assert "Skipped: File line count" in result_lines.raw_content_summary
    assert "exceeds maximum" in result_lines.raw_content_summary
    print("✅ File with too many lines was correctly skipped.")

    print("\n--- Crash Prevention Parsing Test Finished ---")

# --- NEW TEST for Cache and Parallel Processing ---
def test_cache_and_parallel_parsing(intelligence_service: CodeIntelligenceService, caplog):
    """
    Tests the incremental cache and parallel processing functionality.
    """
    print("\n--- Testing Cache and Parallel Parsing ---")
    # Ensure the cache is empty before starting
    intelligence_service.in_memory_cache.clear()

    # --- 1. Test Caching ---
    print("\n--- 1a. Testing Cache Miss ---")
    with caplog.at_level(logging.DEBUG):
        # First parse should be a cache miss, this check happens inside the 'with' block
        intelligence_service.parse_file("polls/models.py", SAMPLE_MODELS_PY)
        assert "Cache miss for 'polls/models.py'" in caplog.text
        assert "Cache hit" not in caplog.text
    # The assertion that the item is now IN the cache should happen *after* the operation.
    assert "polls/models.py" in intelligence_service.in_memory_cache

    print("\n--- 1b. Testing Cache Hit ---")
    caplog.clear()  # Clear logs for the next check
    with caplog.at_level(logging.DEBUG):
        # Second parse of the same content should be a cache hit
        info = intelligence_service.parse_file("polls/models.py", SAMPLE_MODELS_PY)
        assert "Cache hit for 'polls/models.py'" in caplog.text
        assert "Cache miss" not in caplog.text
        assert info is not None
        assert info.file_type == "django_model"

    # --- 2. Test Parallel Processing ---
    print("\n--- 2. Testing Parallel Parsing with Cache ---")
    caplog.clear()
    
    files_to_parse = {
        "polls/models.py": SAMPLE_MODELS_PY,  # This one is already cached
        "polls/views.py": SAMPLE_VIEWS_PY,    # This one is new
    }

    with caplog.at_level(logging.DEBUG):
        results = intelligence_service.parse_files_in_parallel(files_to_parse)
        assert "Cache hit for 'polls/models.py'" in caplog.text
        assert "Cache miss for 'polls/views.py'" in caplog.text
        assert len(results) == 2
        assert results["polls/models.py"] is not None
        assert results["polls/views.py"] is not None and results["polls/views.py"].file_type == "django_view"
        print("✅ Parallel parsing correctly used the cache and parsed new files.")

# --- NEW TEST for Performance Monitoring ---
def test_performance_monitor_decorator(intelligence_service: CodeIntelligenceService):
    """
    Tests that the @time_function decorator correctly records metrics.
    """
    print("\n--- Testing Performance Monitor Integration ---")
    # Reset the monitor before the test to ensure a clean state
    performance_monitor.reset()

    # Call a decorated function
    intelligence_service.parse_file("polls/models.py", SAMPLE_MODELS_PY)

    # Get the performance report
    report = performance_monitor.get_report()

    # Assert that the decorated function's name is in the report
    assert "CodeIntelligenceService.parse_file" in report, "The decorated function 'parse_file' should be in the performance report."
    
    # Check that the report contains expected metric keys
    assert "Calls=" in report
    assert "Total=" in report
    assert "Avg=" in report
    assert "Max=" in report

    # Check that the metrics are plausible
    metrics = performance_monitor.metrics.get("CodeIntelligenceService.parse_file")
    assert metrics is not None
    assert metrics['calls'] == 1
    assert metrics['total_time'] > 0

    print("✅ Performance monitor correctly recorded the function call.")

# This makes the script runnable from the command line.
if __name__ == "__main__":
    # For manual running; use `pytest` for automated testing.
    test_code_intelligence_parsing(None)