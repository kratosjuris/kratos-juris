from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "23f15cd01467"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hearing_contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=40), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "hearings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("process_number", sa.String(length=60), nullable=False),
        sa.Column("promovente", sa.String(length=255), nullable=True),
        sa.Column("promovido", sa.String(length=255), nullable=True),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("modalidade", sa.String(length=80), nullable=True),
        sa.Column("extension_code", sa.String(length=50), nullable=True),
        sa.Column("source_filename", sa.String(length=255), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("client_name_guess", sa.String(length=255), nullable=True),
        sa.Column("notified_client_at", sa.DateTime(), nullable=True),
        sa.Column("notified_team_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),

        sa.UniqueConstraint("process_number", "starts_at", name="uq_hearing_process_datetime"),
    )


    op.create_index("ix_hearings_process_number", "hearings", ["process_number"])
    op.create_index("ix_hearings_starts_at", "hearings", ["starts_at"])
    op.create_index("ix_hearings_client_id", "hearings", ["client_id"])




def downgrade():
    op.drop_constraint("uq_hearing_process_datetime", "hearings", type_="unique")
    op.drop_index("ix_hearings_client_id", table_name="hearings")
    op.drop_index("ix_hearings_starts_at", table_name="hearings")
    op.drop_index("ix_hearings_process_number", table_name="hearings")
    op.drop_table("hearings")
    op.drop_table("hearing_contacts")