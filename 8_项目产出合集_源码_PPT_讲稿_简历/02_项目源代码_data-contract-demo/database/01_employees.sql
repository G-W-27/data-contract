```sql
-- ============================================
-- 第1张表：employees 员工主表
-- 用途：保存员工身份、部门、职位、级别和登录信息
-- ============================================

CREATE TABLE employees (
    employee_id VARCHAR(20) PRIMARY KEY,
    employee_name VARCHAR(50) NOT NULL,
    department VARCHAR(100) NOT NULL,
    position VARCHAR(100) NOT NULL,
    employee_level INTEGER NOT NULL,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_employee_level
        CHECK (employee_level BETWEEN 1 AND 4)
);

-- 员工表字段中文说明
COMMENT ON TABLE employees IS '员工主表';

COMMENT ON COLUMN employees.employee_id IS '员工编号';
COMMENT ON COLUMN employees.employee_name IS '员工姓名';
COMMENT ON COLUMN employees.department IS '所属部门';
COMMENT ON COLUMN employees.position IS '职位';
COMMENT ON COLUMN employees.employee_level IS '员工级别，1-4级';
COMMENT ON COLUMN employees.username IS '登录账号';
COMMENT ON COLUMN employees.password_hash IS '密码哈希，不保存明文密码';
COMMENT ON COLUMN employees.is_active IS '账号是否启用';
COMMENT ON COLUMN employees.created_at IS '创建时间';
COMMENT ON COLUMN employees.updated_at IS '最后更新时间';
```
