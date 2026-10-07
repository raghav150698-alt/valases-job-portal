"""Run explicitly against the dedicated Jobs database, never the recruiter DB."""
from sqlalchemy import create_engine, inspect, text
from valases_jobs.models import Base, Profile
from valases_jobs.settings import Settings

def migrate(engine):
    # Additive baseline upgrade, safe for the existing local pilot database.
    with engine.begin() as connection:
        inspector = inspect(connection)
        upgrades = {'jobs_accounts': {'email_verified':'BOOLEAN NOT NULL DEFAULT false','terms_version':'VARCHAR(30)','terms_accepted_at':'TIMESTAMP'},
                    'jobs_profiles': {'alerts_enabled':'BOOLEAN NOT NULL DEFAULT false','next_digest_at':'TIMESTAMP'}}
        for table, fields in upgrades.items():
            if table not in inspector.get_table_names(): continue
            columns = {item['name'] for item in inspector.get_columns(table)}
            for name, definition in fields.items():
                if name not in columns: connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {definition}'))
        Base.metadata.create_all(connection)
        for index in Profile.__table__.indexes: index.create(connection,checkfirst=True)
        if engine.dialect.name=='postgresql':
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_catalog_search ON jobs_catalog USING GIN (to_tsvector('simple', search_text))"))

if __name__ == "__main__":
    settings = Settings()
    settings.validate_deployment()
    migrate(create_engine(settings.database_url))
    if settings.encryption_key:
        from sqlalchemy.orm import Session
        from sqlalchemy import select
        from valases_jobs.vault import Vault
        vault=Vault(settings)
        with Session(create_engine(settings.database_url)) as db:
            for profile in db.scalars(select(Profile)):
                if not profile.resume_text.startswith('enc:v1:'): profile.resume_text=vault.store(profile.resume_text)
            db.commit()
    print("Valases Jobs schema created in the configured Jobs database")
