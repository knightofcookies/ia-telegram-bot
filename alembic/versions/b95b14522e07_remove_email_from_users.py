"""remove email from Users

Revision ID: b95b14522e07
Revises: 48dc0c9d08d3
Create Date: 2025-03-25 01:05:13.807912

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b95b14522e07'
down_revision: Union[str, None] = '48dc0c9d08d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('Users', 'email')
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('Users', sa.Column('email', sa.VARCHAR(length=255), nullable=True))
    # ### end Alembic commands ###
