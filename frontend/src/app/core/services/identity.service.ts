import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface Permission {
  id: string;
  code: string;
  description: string;
  label?: string | null;
  module?: string | null;
  risk?: string | null;
  /** Crítica: não entra em perfil, só por concessão individual. */
  is_critical?: boolean;
  module_label?: string | null;
  risk_label?: string | null;
}

/** Permissão que a conta tem, e de onde vem (calculado pelo backend). */
export interface EffectivePermission {
  code: string;
  label: string;
  description: string;
  module: string;
  module_label: string;
  risk: string;
  risk_label: string;
  is_critical: boolean;
  sources: string[];
}

export interface CriticalGrant {
  permission: string;
  label: string;
  granted_via: string;
  granted_at: string;
  granted_by_user_id?: string | null;
  reason?: string | null;
}

/** Agrupa por módulo preservando a ordem em que os módulos aparecem (a do catálogo do backend). */
export function groupByModule<T extends { module?: string | null; module_label?: string | null }>(
  items: T[]
): { module: string; label: string; items: T[] }[] {
  const groups = new Map<string, { module: string; label: string; items: T[] }>();
  for (const item of items) {
    const key = item.module || 'outros';
    if (!groups.has(key)) groups.set(key, { module: key, label: item.module_label || key, items: [] });
    groups.get(key)!.items.push(item);
  }
  return [...groups.values()];
}

export interface Role {
  id: string;
  name: string;
  description: string;
  permissions: Permission[];
}

export interface User {
  id: string;
  email: string;
  employee_id: string;
  must_change_password: boolean;
  is_admin: boolean;
  is_active: boolean;
  roles: Role[];
}

@Injectable({
  providedIn: 'root'
})
export class IdentityService {
  private http = inject(HttpClient);
  private baseUrl = '/api/v1/identity';

  // Permissions
  getPermissions(): Observable<Permission[]> {
    return this.http.get<Permission[]>(`${this.baseUrl}/permissions`);
  }

  // Roles
  getRoles(): Observable<Role[]> {
    return this.http.get<Role[]>(`${this.baseUrl}/roles`);
  }

  createRole(data: any): Observable<Role> {
    return this.http.post<Role>(`${this.baseUrl}/roles`, data);
  }

  updateRole(id: string, data: any): Observable<Role> {
    return this.http.patch<Role>(`${this.baseUrl}/roles/${id}`, data);
  }

  deleteRole(id: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/roles/${id}`);
  }

  // Users
  getUsers(): Observable<User[]> {
    return this.http.get<User[]>(`${this.baseUrl}/users`);
  }

  createUser(data: any): Observable<User> {
    return this.http.post<User>(`${this.baseUrl}/users`, data);
  }

  updateUser(id: string, data: any): Observable<User> {
    return this.http.patch<User>(`${this.baseUrl}/users/${id}`, data);
  }

  deleteUser(id: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/users/${id}`);
  }

  resetPassword(id: string, password: string): Observable<void> {
    return this.http.patch<void>(`${this.baseUrl}/users/${id}/password`, { password });
  }

  // Acesso efetivo e permissões críticas (concessão individual)
  getEffectiveAccess(userId: string): Observable<EffectivePermission[]> {
    return this.http.get<EffectivePermission[]>(`${this.baseUrl}/users/${userId}/effective-access`);
  }

  getCriticalGrants(userId: string): Observable<CriticalGrant[]> {
    return this.http.get<CriticalGrant[]>(`${this.baseUrl}/users/${userId}/critical-permissions`);
  }

  grantCritical(userId: string, permission: string, reason: string): Observable<CriticalGrant[]> {
    return this.http.post<CriticalGrant[]>(`${this.baseUrl}/users/${userId}/critical-permissions`, { permission, reason });
  }

  revokeCritical(userId: string, permission: string, reason: string): Observable<CriticalGrant[]> {
    return this.http.request<CriticalGrant[]>('DELETE', `${this.baseUrl}/users/${userId}/critical-permissions/${permission}`, {
      body: { reason }
    });
  }
}
