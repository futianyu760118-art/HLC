export type AccountType = 'hrm' | 'employee_portal';

export type UserRole =
  | 'platform_admin'
  | 'admin'
  | 'hr_admin'
  | 'recruiter'
  | 'manager'
  | 'employee'
  | 'finance'
  | 'executive'
  | 'viewer';

export interface AuthUser {
  id?: string;
  email?: string;
  name?: string;
  role?: UserRole;
  tenantId?: string | null;
  tenantSlug?: string | null;
  tenantName?: string | null;
  employeeId?: string | null;
  employee_id?: string | null;
  employeeNo?: string | null;
  accountType?: AccountType;
  mustChangePassword?: boolean;
  isPlatformAdmin?: boolean;
  avatarUrl?: string;
}

export interface LoginResponse {
  token: string;
  user: AuthUser;
}
