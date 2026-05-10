from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('trails', '0003_add_trail_colour'),
    ]

    operations = [
        migrations.AddField(
            model_name='trail',
            name='highway_type',
            field=models.CharField(blank=True, default='trail', max_length=30),
        ),
    ]
