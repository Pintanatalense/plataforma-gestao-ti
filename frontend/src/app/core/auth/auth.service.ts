import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable, catchError, of, tap } from 'rxjs';
import { Router } from '@angular/router';

interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface UserAccount {
  id: string;
  email: string;
  must_change_password: boolean;
  is_admin: boolean;
  roles: any[];
}

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  private http = inject(HttpClient);
  private router = inject(Router);
  
  private apiUrl = '/api/v1/identity';
  
  private currentUserSubject = new BehaviorSubject<UserAccount | null>(null);
  public currentUser$ = this.currentUserSubject.asObservable();

  constructor() {
    this.loadUserFromStorage();
  }

  get token(): string | null {
    return localStorage.getItem('access_token');
  }

  get currentUserValue(): UserAccount | null {
    return this.currentUserSubject.value;
  }

  login(username: string, password: string): Observable<TokenResponse> {
    const formData = new URLSearchParams();
    formData.set('username', username);
    formData.set('password', password);

    return this.http.post<TokenResponse>(`${this.apiUrl}/login`, formData.toString(), {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    }).pipe(
      tap(response => {
        localStorage.setItem('access_token', response.access_token);
        this.fetchCurrentUser().subscribe();
      })
    );
  }

  logout() {
    localStorage.removeItem('access_token');
    this.currentUserSubject.next(null);
    this.router.navigate(['/login']);
  }

  getSetupStatus(): Observable<{setup_required: boolean}> {
    return this.http.get<{setup_required: boolean}>(`${this.apiUrl}/setup/status`);
  }

  setupFirstAdmin(data: any): Observable<TokenResponse> {
    return this.http.post<TokenResponse>(`${this.apiUrl}/setup`, data).pipe(
      tap(response => {
        localStorage.setItem('access_token', response.access_token);
        this.fetchCurrentUser().subscribe();
      })
    );
  }

  fetchCurrentUser(): Observable<UserAccount> {
    return this.http.get<UserAccount>(`${this.apiUrl}/me`).pipe(
      tap(user => this.currentUserSubject.next(user))
    );
  }

  /** Retorna o usuário em memória ou o carrega via /me; null se a sessão for inválida. */
  ensureUser(): Observable<UserAccount | null> {
    const current = this.currentUserValue;
    if (current) return of(current);
    if (!this.token) return of(null);
    return this.fetchCurrentUser().pipe(
      catchError(() => {
        localStorage.removeItem('access_token');
        return of(null);
      })
    );
  }

  changeOwnPassword(currentPassword: string, newPassword: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/me/password`, {
      current_password: currentPassword,
      new_password: newPassword
    }).pipe(
      tap(() => this.fetchCurrentUser().subscribe())
    );
  }

  private loadUserFromStorage() {
    if (this.token) {
      this.fetchCurrentUser().subscribe({
        error: () => this.logout() // Token inválido
      });
    }
  }

  hasPermission(requiredPermission: string): boolean {
    const user = this.currentUserValue;
    if (!user) return false;
    if (user.is_admin) return true;
    
    // permissions are nested in roles
    const permissions = new Set<string>();
    user.roles?.forEach(role => {
      role.permissions?.forEach((p: any) => permissions.add(p.code));
    });
    
    return permissions.has(requiredPermission);
  }
}
