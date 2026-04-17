from django.db import migrations


def seed_roles_and_feedback(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    FeedbackQuestion = apps.get_model("clinic", "FeedbackQuestion")

    for name in ["receptionist", "therapist", "doctor"]:
        Group.objects.get_or_create(name=name)

    if FeedbackQuestion.objects.count() == 0:
        prompts = [
            "I felt listened to and understood during the session.",
            "The session helped me understand my situation better.",
            "I am satisfied with the professionalism and confidentiality.",
            "I would recommend KEWOTA services to someone in need.",
        ]
        for idx, prompt in enumerate(prompts, start=1):
            FeedbackQuestion.objects.create(prompt=prompt, sort_order=idx, is_active=True)


def unseed_roles_and_feedback(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    FeedbackQuestion = apps.get_model("clinic", "FeedbackQuestion")

    Group.objects.filter(name__in=["receptionist", "therapist", "doctor"]).delete()
    FeedbackQuestion.objects.filter(prompt__in=[
        "I felt listened to and understood during the session.",
        "The session helped me understand my situation better.",
        "I am satisfied with the professionalism and confidentiality.",
        "I would recommend KEWOTA services to someone in need.",
    ]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("clinic", "0003_feedbackquestion_feedbacksubmission_and_more"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(seed_roles_and_feedback, reverse_code=unseed_roles_and_feedback),
    ]

