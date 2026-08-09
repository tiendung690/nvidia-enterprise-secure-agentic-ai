INSERT INTO operational_order (
    order_id, tenant_id, status, delivered_at, product_category,
    customer_reference, record_version, updated_at
) VALUES
    ('ABC-123', 'tenant-a', 'Delivered', '2026-08-01T10:30:00Z',
     'electronics', 'customer.a@example.com', 7, '2026-08-05T08:00:00Z'),
    ('XYZ-999', 'tenant-b', 'In Transit', NULL,
     'home', 'customer.b@example.com', 3, '2026-08-05T08:10:00Z')
ON CONFLICT (tenant_id, order_id) DO UPDATE SET
    status = excluded.status,
    delivered_at = excluded.delivered_at,
    product_category = excluded.product_category,
    customer_reference = excluded.customer_reference,
    record_version = excluded.record_version,
    updated_at = excluded.updated_at;
