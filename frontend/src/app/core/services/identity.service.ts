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
}
