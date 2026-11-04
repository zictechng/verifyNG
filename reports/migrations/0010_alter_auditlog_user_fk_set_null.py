from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0009_evidencedossier_last_scanned_at_and_more'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            ALTER TABLE reports_auditlog 
                DROP CONSTRAINT IF EXISTS reports_auditlog_performed_by_id_41048a7a_fk_users_user_id;
            ALTER TABLE reports_auditlog 
                ADD CONSTRAINT reports_auditlog_performed_by_id_41048a7a_fk_users_user_id 
                FOREIGN KEY (performed_by_id) REFERENCES users_user(id) ON DELETE SET NULL;

            ALTER TABLE reports_auditlog 
                DROP CONSTRAINT IF EXISTS reports_auditlog_target_user_id_4c406f54_fk_users_user_id;
            ALTER TABLE reports_auditlog 
                ADD CONSTRAINT reports_auditlog_target_user_id_4c406f54_fk_users_user_id 
                FOREIGN KEY (target_user_id) REFERENCES users_user(id) ON DELETE SET NULL;
            """,
            reverse_sql="""
            ALTER TABLE reports_auditlog 
                DROP CONSTRAINT IF EXISTS reports_auditlog_performed_by_id_41048a7a_fk_users_user_id;
            ALTER TABLE reports_auditlog 
                ADD CONSTRAINT reports_auditlog_performed_by_id_41048a7a_fk_users_user_id 
                FOREIGN KEY (performed_by_id) REFERENCES users_user(id) ON DELETE NO ACTION;

            ALTER TABLE reports_auditlog 
                DROP CONSTRAINT IF EXISTS reports_auditlog_target_user_id_4c406f54_fk_users_user_id;
            ALTER TABLE reports_auditlog 
                ADD CONSTRAINT reports_auditlog_target_user_id_4c406f54_fk_users_user_id 
                FOREIGN KEY (target_user_id) REFERENCES users_user(id) ON DELETE NO ACTION;
            """
        ),
    ]
