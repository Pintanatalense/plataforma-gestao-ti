import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable, catchError, of, tap, switchMap, map } from 'rxjs';
import { Router } from '@angular/router';

interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface UserAccount {
  id: string;
  email: string;
  employee_id?: string | null;
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
  
  private readonly TOKEN_KEY = 'access_token';
  private readonly USER_KEY = 'current_user';

  private currentUserSubject: BehaviorSubject<UserAccount | null>;
  public currentUser$: Observable<UserAccount | null>;

  constructor() {
    const cachedUser = this.getStoredUser();
    this.currentUserSubject = new BehaviorSubject<UserAccount | null>(cachedUser);
    this.currentUser$ = this.currentUserSubject.asObservable();

    if (this.token) {
      this.revalidateSession();
    }
  }

  private getStoredUser(): UserAccount | null {
    try {
      const raw = localStorage.getItem(this.USER_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch {
      localStorage.removeItem(this.USER_KEY);
      return null;
    }
  }

  get token(): string | null {
    return localStorage.getItem(this.TOKEN_KEY);
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
        localStorage.setItem(this.TOKEN_KEY, response.access_token);
      }),
      switchMap(response => {
        return this.fetchCurrentUser().pipe(
          map(() => response)
        );
      })
    );
  }

  logout() {
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.USER_KEY);
    this.currentUserSubject.next(null);
    this.router.navigate(['/login']);
  }

  getSetupStatus(): Observable<{setup_required: boolean}> {
    return this.http.get<{setup_required: boolean}>(`${this.apiUrl}/setup/status`);
  }

  setupFirstAdmin(data: any): Observable<TokenResponse> {
    return this.http.post<TokenResponse>(`${this.apiUrl}/setup`, data).pipe(
      tap(response => {
        localStorage.setItem(this.TOKEN_KEY, response.access_token);
      }),
      switchMap(response => {
        return this.fetchCurrentUser().pipe(
          map(() => response)
        );
      })
    );
  }

  fetchCurrentUser(): Observable<UserAccount> {
    return this.http.get<UserAccount>(`${this.apiUrl}/me`).pipe(
      tap(user => {
        this.currentUserSubject.next(user);
        try {
          localStorage.setItem(this.USER_KEY, JSON.stringify(user));
        } catch (e) {
          console.warn('Could not cache user in localStorage', e);
        }
      })
    );
  }

  /** Retorna o usuário em memória/cache ou o carrega via /me; null se a sessão for inválida. */
  ensureUser(): Observable<UserAccount | null> {
    const current = this.currentUserValue;
    if (current && this.token) {
      // Sessão válida recuperada do cache instantaneamente.
      // Revalida em background de forma transparente.
      this.revalidateSession();
      return of(current);
    }
    if (!this.token) return of(null);
    return this.fetchCurrentUser().pipe(
      catchError((err) => {
        if (err?.status === 401) {
          this.logout();
        }
        return of(null);
      })
    );
  }

  changeOwnPassword(currentPassword: string, newPassword: string): Observable<UserAccount> {
    return this.http.post<UserAccount>(`${this.apiUrl}/me/password`, {
      current_password: currentPassword,
      new_password: newPassword
    }).pipe(
      tap((user) => {
        this.currentUserSubject.next(user);
        try {
          localStorage.setItem(this.USER_KEY, JSON.stringify(user));
        } catch {}
      })
    );
  }

  private revalidateSession() {
    this.fetchCurrentUser().subscribe({
      error: (err) => {
        if (err?.status === 401) {
          this.logout();
        }
      }
    });
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
