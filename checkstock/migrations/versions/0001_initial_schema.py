# -*- coding: utf-8 -*-
"""initial schema

Revision ID: 0001
Revises: 
"""
from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: Optional[str] = None
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table('products',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sku', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_products')),
    sa.UniqueConstraint('sku', name=op.f('uq_products_sku'))
    )
    op.create_table('warehouses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_warehouses'))
    )
    op.create_index(op.f('ix_warehouses_created_at'), 'warehouses', ['created_at'], unique=False)
    op.create_index('uq_warehouses_active_name', 'warehouses', [sa.text('lower(name)')], unique=True, postgresql_where=sa.text('NOT is_deleted'))
    op.create_table('fbo_shipments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('warehouse_id', sa.Integer(), nullable=False),
    sa.Column('qty', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('in_transit', 'received', 'cancelled', name='fbo_status', native_enum=False, create_constraint=True, length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('qty > 0', name=op.f('ck_fbo_shipments_qty_positive')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_fbo_shipments_product_id_products')),
    sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'], name=op.f('fk_fbo_shipments_warehouse_id_warehouses')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_fbo_shipments'))
    )
    op.create_index(op.f('ix_fbo_shipments_created_at'), 'fbo_shipments', ['created_at'], unique=False)
    op.create_index(op.f('ix_fbo_shipments_product_id'), 'fbo_shipments', ['product_id'], unique=False)
    op.create_index(op.f('ix_fbo_shipments_status'), 'fbo_shipments', ['status'], unique=False)
    op.create_index(op.f('ix_fbo_shipments_warehouse_id'), 'fbo_shipments', ['warehouse_id'], unique=False)
    op.create_table('fbs_orders',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('warehouse_id', sa.Integer(), nullable=False),
    sa.Column('qty', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('reserved', 'shipped', 'delivered', 'cancelled', name='fbs_status', native_enum=False, create_constraint=True, length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('shipped_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('qty > 0', name=op.f('ck_fbs_orders_qty_positive')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_fbs_orders_product_id_products')),
    sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'], name=op.f('fk_fbs_orders_warehouse_id_warehouses')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_fbs_orders'))
    )
    op.create_index(op.f('ix_fbs_orders_created_at'), 'fbs_orders', ['created_at'], unique=False)
    op.create_index(op.f('ix_fbs_orders_product_id'), 'fbs_orders', ['product_id'], unique=False)
    op.create_index(op.f('ix_fbs_orders_status'), 'fbs_orders', ['status'], unique=False)
    op.create_index('ix_fbs_orders_warehouse_status', 'fbs_orders', ['warehouse_id', 'status'], unique=False)
    op.create_table('inventory',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('warehouse_id', sa.Integer(), nullable=False),
    sa.Column('physical_qty', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('reserved_fbs_qty', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('physical_qty >= 0', name=op.f('ck_inventory_physical_nonneg')),
    sa.CheckConstraint('reserved_fbs_qty <= physical_qty', name=op.f('ck_inventory_reserved_lte_physical')),
    sa.CheckConstraint('reserved_fbs_qty >= 0', name=op.f('ck_inventory_reserved_nonneg')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_inventory_product_id_products')),
    sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'], name=op.f('fk_inventory_warehouse_id_warehouses')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory')),
    sa.UniqueConstraint('product_id', 'warehouse_id', name=op.f('uq_inventory_product_id_warehouse_id'))
    )
    op.create_index(op.f('ix_inventory_product_id'), 'inventory', ['product_id'], unique=False)
    op.create_index(op.f('ix_inventory_warehouse_id'), 'inventory', ['warehouse_id'], unique=False)
    op.create_table('movements',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('from_warehouse_id', sa.Integer(), nullable=False),
    sa.Column('to_warehouse_id', sa.Integer(), nullable=False),
    sa.Column('qty', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('in_transit', 'confirmed', 'cancelled', name='movement_status', native_enum=False, create_constraint=True, length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('from_warehouse_id <> to_warehouse_id', name=op.f('ck_movements_distinct_warehouses')),
    sa.CheckConstraint('qty > 0', name=op.f('ck_movements_qty_positive')),
    sa.ForeignKeyConstraint(['from_warehouse_id'], ['warehouses.id'], name=op.f('fk_movements_from_warehouse_id_warehouses')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_movements_product_id_products')),
    sa.ForeignKeyConstraint(['to_warehouse_id'], ['warehouses.id'], name=op.f('fk_movements_to_warehouse_id_warehouses')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_movements'))
    )
    op.create_index(op.f('ix_movements_created_at'), 'movements', ['created_at'], unique=False)
    op.create_index(op.f('ix_movements_from_warehouse_id'), 'movements', ['from_warehouse_id'], unique=False)
    op.create_index(op.f('ix_movements_product_id'), 'movements', ['product_id'], unique=False)
    op.create_index(op.f('ix_movements_status'), 'movements', ['status'], unique=False)
    op.create_index('ix_movements_to_warehouse_status', 'movements', ['to_warehouse_id', 'status'], unique=False)
    op.create_table('operation_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('operation', sa.String(length=32), nullable=False),
    sa.Column('document_type', sa.String(length=16), nullable=True),
    sa.Column('document_id', sa.Integer(), nullable=True),
    sa.Column('product_id', sa.Integer(), nullable=True),
    sa.Column('product_sku', sa.String(length=64), nullable=True),
    sa.Column('qty', sa.Integer(), nullable=True),
    sa.Column('source', sa.String(length=128), nullable=True),
    sa.Column('destination', sa.String(length=128), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_operation_log_product_id_products')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_operation_log'))
    )
    op.create_index(op.f('ix_operation_log_created_at'), 'operation_log', ['created_at'], unique=False)
    op.create_index(op.f('ix_operation_log_operation'), 'operation_log', ['operation'], unique=False)
    op.create_index(op.f('ix_operation_log_product_id'), 'operation_log', ['product_id'], unique=False)
    op.create_table('receipts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('warehouse_id', sa.Integer(), nullable=False),
    sa.Column('qty', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('qty > 0', name=op.f('ck_receipts_qty_positive')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_receipts_product_id_products')),
    sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'], name=op.f('fk_receipts_warehouse_id_warehouses')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_receipts'))
    )
    op.create_index(op.f('ix_receipts_created_at'), 'receipts', ['created_at'], unique=False)
    op.create_index(op.f('ix_receipts_product_id'), 'receipts', ['product_id'], unique=False)
    op.create_index(op.f('ix_receipts_warehouse_id'), 'receipts', ['warehouse_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_receipts_warehouse_id'), table_name='receipts')
    op.drop_index(op.f('ix_receipts_product_id'), table_name='receipts')
    op.drop_index(op.f('ix_receipts_created_at'), table_name='receipts')
    op.drop_table('receipts')
    op.drop_index(op.f('ix_operation_log_product_id'), table_name='operation_log')
    op.drop_index(op.f('ix_operation_log_operation'), table_name='operation_log')
    op.drop_index(op.f('ix_operation_log_created_at'), table_name='operation_log')
    op.drop_table('operation_log')
    op.drop_index('ix_movements_to_warehouse_status', table_name='movements')
    op.drop_index(op.f('ix_movements_status'), table_name='movements')
    op.drop_index(op.f('ix_movements_product_id'), table_name='movements')
    op.drop_index(op.f('ix_movements_from_warehouse_id'), table_name='movements')
    op.drop_index(op.f('ix_movements_created_at'), table_name='movements')
    op.drop_table('movements')
    op.drop_index(op.f('ix_inventory_warehouse_id'), table_name='inventory')
    op.drop_index(op.f('ix_inventory_product_id'), table_name='inventory')
    op.drop_table('inventory')
    op.drop_index('ix_fbs_orders_warehouse_status', table_name='fbs_orders')
    op.drop_index(op.f('ix_fbs_orders_status'), table_name='fbs_orders')
    op.drop_index(op.f('ix_fbs_orders_product_id'), table_name='fbs_orders')
    op.drop_index(op.f('ix_fbs_orders_created_at'), table_name='fbs_orders')
    op.drop_table('fbs_orders')
    op.drop_index(op.f('ix_fbo_shipments_warehouse_id'), table_name='fbo_shipments')
    op.drop_index(op.f('ix_fbo_shipments_status'), table_name='fbo_shipments')
    op.drop_index(op.f('ix_fbo_shipments_product_id'), table_name='fbo_shipments')
    op.drop_index(op.f('ix_fbo_shipments_created_at'), table_name='fbo_shipments')
    op.drop_table('fbo_shipments')
    op.drop_index('uq_warehouses_active_name', table_name='warehouses', postgresql_where=sa.text('NOT is_deleted'))
    op.drop_index(op.f('ix_warehouses_created_at'), table_name='warehouses')
    op.drop_table('warehouses')
    op.drop_table('products')
