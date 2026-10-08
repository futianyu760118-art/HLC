-- 人才分析和能力模型相关表

-- 能力评估记录表
CREATE TABLE IF NOT EXISTS competency_evaluations (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL,
    employee_id VARCHAR(36) NOT NULL,
    category VARCHAR(50) NOT NULL COMMENT '能力类别',
    competency_name VARCHAR(100) NOT NULL COMMENT '能力名称',
    score INT NOT NULL COMMENT '评分 0-100',
    evaluator_id VARCHAR(36) COMMENT '评估人',
    evaluation_date DATE NOT NULL,
    comments TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tenant (tenant_id),
    INDEX idx_employee (employee_id),
    INDEX idx_date (evaluation_date),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='能力评估记录';

-- 继任计划表
CREATE TABLE IF NOT EXISTS succession_plans (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL,
    position_id VARCHAR(36) NOT NULL COMMENT '关键岗位',
    incumbent_id VARCHAR(36) COMMENT '现任者',
    successor_id VARCHAR(36) NOT NULL COMMENT '继任者',
    readiness VARCHAR(20) COMMENT 'ready/developing/long-term',
    development_plan TEXT COMMENT '培养计划',
    target_date DATE COMMENT '预计就绪日期',
    status VARCHAR(20) DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_tenant (tenant_id),
    INDEX idx_position (position_id),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (position_id) REFERENCES positions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='继任计划';

-- 离职风险预测记录表
CREATE TABLE IF NOT EXISTS turnover_predictions (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL,
    employee_id VARCHAR(36) NOT NULL,
    risk_score INT NOT NULL COMMENT '风险评分 0-100',
    risk_level VARCHAR(20) NOT NULL COMMENT 'high/medium/low',
    risk_factors JSON COMMENT '风险因素列表',
    recommendation TEXT COMMENT '保留建议',
    prediction_date DATE NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tenant (tenant_id),
    INDEX idx_employee (employee_id),
    INDEX idx_risk (risk_level),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='离职风险预测';

-- IDP个人发展计划表
CREATE TABLE IF NOT EXISTS individual_development_plans (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL,
    employee_id VARCHAR(36) NOT NULL,
    goals JSON COMMENT '发展目标列表',
    actions JSON COMMENT '行动计划列表',
    status VARCHAR(20) DEFAULT 'active',
    start_date DATE,
    review_date DATE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_tenant (tenant_id),
    INDEX idx_employee (employee_id),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='个人发展计划';
