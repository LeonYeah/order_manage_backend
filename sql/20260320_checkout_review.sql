ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS review_status ENUM('未审核','已驳回','已通过') NOT NULL DEFAULT '已通过' AFTER settlement_at,
  ADD COLUMN IF NOT EXISTS reject_reason VARCHAR(500) NULL AFTER review_status,
  ADD COLUMN IF NOT EXISTS rejected_by BIGINT NULL AFTER reject_reason,
  ADD COLUMN IF NOT EXISTS rejected_at DATETIME NULL AFTER rejected_by,
  ADD COLUMN IF NOT EXISTS resubmitted_at DATETIME NULL AFTER rejected_at;

UPDATE orders
SET review_status = '未审核'
WHERE settlement_status = '未结账'
  AND (review_status IS NULL OR review_status = '');

UPDATE orders
SET review_status = '未审核'
WHERE review_status = '待审核';

UPDATE orders
SET review_status = '已通过'
WHERE settlement_status = '已结账'
  AND (review_status IS NULL OR review_status = '');

UPDATE orders
SET reject_reason = NULL,
    rejected_by = NULL,
    rejected_at = NULL
WHERE review_status <> '已驳回';
