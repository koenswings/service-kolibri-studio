# -*- coding: utf-8 -*-
# Generated by Django 1.11.15 on 2019-02-28 20:19
from __future__ import unicode_literals

import uuid

import django.contrib.postgres.fields.jsonb
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations
from django.db import models

import contentcuration.models


class Migration(migrations.Migration):
    dependencies = [
        ('contentcuration', '0004_remove_rename_json_field'),
    ]

    operations = [
        migrations.CreateModel(
            name='Task',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('task_type', models.CharField(max_length=50)),
                ('created', models.DateTimeField(default=django.utils.timezone.now)),
                ('status', models.CharField(max_length=10)),
                ('is_progress_tracking', models.BooleanField(default=False)),
                ('metadata', django.contrib.postgres.fields.jsonb.JSONField()),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='task', to=settings.AUTH_USER_MODEL)),
                ('task_id', contentcuration.models.UUIDField(db_index=True, default=uuid.uuid4, max_length=32)),
            ],
        ),
        migrations.AlterField(
            model_name='formatpreset',
            name='id',
            field=models.CharField(choices=[('high_res_video', 'High Resolution'), ('low_res_video', 'Low Resolution'), ('video_thumbnail', 'Thumbnail'), ('video_subtitle', 'Subtitle'), ('video_dependency', 'Video (dependency)'), ('audio', 'Audio'), ('audio_thumbnail', 'Thumbnail'), ('document', 'Document'), ('epub', 'ePub Document'), ('document_thumbnail', 'Thumbnail'), ('exercise', 'Exercise'), ('exercise_thumbnail', 'Thumbnail'), ('exercise_image', 'Exercise Image'), ('exercise_graphie', 'Exercise Graphie'), ('channel_thumbnail', 'Channel Thumbnail'), ('topic_thumbnail', 'Thumbnail'), ('html5_zip', 'HTML5 Zip'), ('html5_dependency', 'HTML5 Dependency (Zip format)'), ('html5_thumbnail', 'HTML5 Thumbnail')], max_length=150, primary_key=True, serialize=False),
        ),
    ]
