-- 编制管理数据库迁移脚本
-- 为 departments 和 positions 表添加编制字段

-- 为 departments 表添加编制字段
ALTER TABLE departments ADD COLUMN headcount_plan INT DEFAULT 0 NOT NULL COMMENT '编制人数';
ALTER TABLE departments ADD COLUMN headcount_actual INT DEFAULT 0 NOT NULL COMMENT '实际人数';
ALTER TABLE departments ADD COLUMN headcount_updated_at DATETIME COMMENT '编制更新时间';

-- 为 positions 表添加编制字段
ALTER TABLE positions ADD COLUMN headcount_plan INT DEFAULT 0 NOT NULL COMMENT '编制人数';

-- 创建编制历史记录表（可选）
CREATE TABLE IF NOT EXISTS headcount_history (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL,
    department_id VARCHAR(36),
    position_id VARCHAR(36),
    old_plan INT DEFAULT 0,
    new_plan INT NOT NULL,
    change_reason VARCHAR(200),
    operator_id VARCHAR(36),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tenant (tenant_id),
    INDEX idx_department (department_id),
    INDEX idx_created (created_at),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (operator_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='编制变更历史';
