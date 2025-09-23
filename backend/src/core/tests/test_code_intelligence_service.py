# src/core/tests/test_code_intelligence_service.py
import unittest
import shutil
from pathlib import Path

from src.core.code_intelligence_service import CodeIntelligenceService
from src.core.project_models import ErrorType

class TestCodeIntelligenceService(unittest.TestCase):
    """
    Unit tests for the CodeIntelligenceService.
    These tests verify that the service can accurately parse code files
    and extract structured information.
    """

    def setUp(self):
        """Set up a temporary project directory and the service instance."""
        self.test_dir = Path("temp_test_project_for_cis").resolve()
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir()

        self.code_intel_service = CodeIntelligenceService(project_root=self.test_dir)
        print(f"\n--- Running test: {self._testMethodName} ---")

    def tearDown(self):
        """Clean up the temporary directory."""
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_parse_django_model_file(self):
        """
        Verify that a Django models.py file is parsed correctly into
        DjangoModel and DjangoModelField Pydantic models.
        """
        # Arrange: Define the content of a sample models.py file
        models_py_content = """
from django.db import models
from django.contrib.auth.models import User

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class Post(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField(null=True, blank=True)
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='posts')
    category = models.ForeignKey('Category', on_delete=models.SET_NULL, null=True)
    is_published = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
"""
        file_path = "blog/models.py"

        # Act: Parse the file content
        file_info = self.code_intel_service.parse_file(file_path, models_py_content)

        # Assert: Check the parsed structure
        self.assertIsNotNone(file_info)
        self.assertEqual(file_info.file_type, "django_model")
        self.assertIsNotNone(file_info.django_model_details)

        # Check the Post model
        post_model = next((m for m in file_info.django_model_details.models if m.name == "Post"), None)
        self.assertIsNotNone(post_model)
        self.assertEqual(post_model.name, "Post")
        self.assertIn("models.Model", post_model.bases)
        self.assertEqual(len(post_model.django_fields), 5)

        # Check a simple CharField
        title_field = next((f for f in post_model.django_fields if f.name == "title"), None)
        self.assertIsNotNone(title_field)
        self.assertEqual(title_field.field_type, "CharField")
        self.assertEqual(title_field.max_length, 200)

        # Check a complex ForeignKey
        author_field = next((f for f in post_model.django_fields if f.name == "author"), None)
        self.assertIsNotNone(author_field)
        self.assertEqual(author_field.field_type, "ForeignKey")
        self.assertEqual(author_field.related_model_name, "User")
        self.assertEqual(author_field.on_delete, "models.CASCADE")
        self.assertEqual(author_field.args.get("related_name"), "posts")

        # Check the Meta class options
        self.assertIn("ordering", post_model.meta_options)
        self.assertEqual(post_model.meta_options["ordering"], ['-created_at'])

        # Check the Category model
        category_model = next((m for m in file_info.django_model_details.models if m.name == "Category"), None)
        self.assertIsNotNone(category_model)
        self.assertEqual(len(category_model.methods), 1)
        self.assertEqual(category_model.methods[0].name, "__str__")

    def test_parse_django_view_file(self):
        """
        Verify that a Django views.py file is parsed correctly, extracting
        view functions, rendered templates, model queries, and more.
        """
        # Arrange: Define the content of a sample views.py file
        views_py_content = """
from django.shortcuts import render, redirect
from django.views import View
from .models import Post, Category
from .forms import PostForm
from django.http import Http404
from django.views.decorators.http import require_http_methods

def post_list(request):
    posts = Post.objects.all().order_by('-created_at')
    return render(request, 'blog/post_list.html', {'posts': posts})

@require_http_methods(["POST"])
def create_post(request):
    if request.method == 'POST':
        form = PostForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('blog:post_list')
    else:
        form = PostForm()
    return render(request, 'blog/post_form.html', {'form': form})
"""
        file_path = "blog/views.py"

        # Act: Parse the file content
        file_info = self.code_intel_service.parse_file(file_path, views_py_content)

        # Assert: Check the parsed structure
        self.assertIsNotNone(file_info)
        self.assertEqual(file_info.file_type, "django_view")
        self.assertIsNotNone(file_info.django_view_details)
        self.assertEqual(len(file_info.django_view_details.views), 2) # post_list and create_post

        # Check the 'create_post' function-based view
        create_post_view = next((v for v in file_info.django_view_details.views if v.name == "create_post"), None)
        self.assertIsNotNone(create_post_view)
        self.assertEqual(create_post_view.rendered_templates, ['blog/post_form.html'])
        self.assertEqual(create_post_view.uses_forms, ['PostForm'])
        self.assertEqual(create_post_view.redirects_to_url_name, 'blog:post_list')
        self.assertIn('POST', create_post_view.allowed_http_methods)

    def test_parse_django_urls_file(self):
        """
        Verify that a Django urls.py file is parsed correctly, extracting
        app_name and url patterns.
        """
        # Arrange: Define the content of a sample urls.py file
        urls_py_content = """
from django.urls import path, include
from . import views

app_name = 'blog'

urlpatterns = [
    path('', views.post_list, name='post_list'),
    path('post/<int:pk>/', views.post_detail, name='post_detail'),
    path('api/', include('blog.api.urls')),
]
"""
        file_path = "blog/urls.py"

        # Act: Parse the file content
        file_info = self.code_intel_service.parse_file(file_path, urls_py_content)

        # Assert: Check the parsed structure
        self.assertIsNotNone(file_info)
        self.assertEqual(file_info.file_type, "django_urls")
        self.assertIsNotNone(file_info.django_urls_details)

        # Check app_name
        self.assertEqual(file_info.django_urls_details.app_name, "blog")

        # Check url_patterns
        self.assertEqual(len(file_info.django_urls_details.url_patterns), 2)
        post_list_pattern = next((p for p in file_info.django_urls_details.url_patterns if p.name == "post_list"), None)
        self.assertIsNotNone(post_list_pattern)
        self.assertEqual(post_list_pattern.view_reference, "views.post_list")

        # Check includes
        self.assertEqual(len(file_info.django_urls_details.includes), 1)
        self.assertEqual(file_info.django_urls_details.includes[0].included_urlconf, "blog.api.urls")

    def test_parse_django_forms_file(self):
        """
        Verify that a Django forms.py file is parsed correctly, extracting
        Form and ModelForm classes and their fields.
        """
        # Arrange: Define the content of a sample forms.py file
        forms_py_content = """
from django import forms
from .models import Post

class ContactForm(forms.Form):
    name = forms.CharField(max_length=100, required=True)
    email = forms.EmailField(label='Your email')
    message = forms.CharField(widget=forms.Textarea)

class PostForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ['title', 'content', 'category']
"""
        file_path = "blog/forms.py"

        # Act: Parse the file content
        file_info = self.code_intel_service.parse_file(file_path, forms_py_content)

        # Assert: Check the parsed structure
        self.assertIsNotNone(file_info)
        self.assertEqual(file_info.file_type, "django_form")
        self.assertIsNotNone(file_info.django_form_details)
        self.assertEqual(len(file_info.django_form_details.forms), 2)

        # Check the ModelForm
        post_form = next((f for f in file_info.django_form_details.forms if f.name == "PostForm"), None)
        self.assertIsNotNone(post_form)
        self.assertIn("forms.ModelForm", post_form.bases)
        self.assertEqual(post_form.meta_model, "Post")
        self.assertEqual(post_form.meta_fields, ["'title'", "'content'", "'category'"])

        # Check the regular Form
        contact_form = next((f for f in file_info.django_form_details.forms if f.name == "ContactForm"), None)
        self.assertIsNotNone(contact_form)
        self.assertIn("forms.Form", contact_form.bases)
        self.assertEqual(len(contact_form.form_fields), 3)
        email_field = next((f for f in contact_form.form_fields if f.name == "email"), None)
        self.assertIsNotNone(email_field)
        self.assertEqual(email_field.field_type, "EmailField")
        self.assertEqual(email_field.args.get('label'), 'Your email')

if __name__ == '__main__':
    unittest.main()