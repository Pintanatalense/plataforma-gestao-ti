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
  /** Permissões críticas concedidas individualmente (nunca vêm de perfil). */
  critical_permissions?: string[];
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

  private readonly RETURN_URL_KEY = 'return_url';

  /** Guarda a página em que a sessão caiu para voltar a ela depois do login (só caminhos internos). */
  rememberReturnUrl(url: string): void {
    if (!this.isSafeReturnUrl(url) || ['/login', '/setup', '/change-password'].some((p) => url.startsWith(p))) return;
    try {
      sessionStorage.setItem(this.RETURN_URL_KEY, url);
    } catch {
      // armazenamento indisponível (modo privado): segue sem guardar
    }
  }

  /** Devolve (e esquece) a página guardada; nulo se não houver ou se não for um caminho interno. */
  takeReturnUrl(): string | null {
    try {
      const url = sessionStorage.getItem(this.RETURN_URL_KEY);
      sessionStorage.removeItem(this.RETURN_URL_KEY);
      return url && this.isSafeReturnUrl(url) ? url : null;
    } catch {
      return null;
    }
  }

  // Evita redirecionamento aberto: só caminho interno ("/x"), nunca "//host" nem esquema ("http:", "javascript:").
  private isSafeReturnUrl(url: string): boolean {
    return url.length <= 2048 && /^\/(?!\/)[^\s]*$/.test(url) && !url.includes('://') && !url.includes('\\');
  }

  logout() {
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.USER_KEY);
    this.currentUserSubject.next(null);
    this.router.navigate(['/login']);
  }

  /** Recuperação de senha por e-mail (ADR-018): só aparece na tela quando o administrador a ativou. */
  passwordResetStatus(): Observable<{ enabled: boolean }> {
    return this.http.get<{ enabled: boolean }>(`${this.apiUrl}/password-reset/status`);
  }

  requestPasswordReset(email: string): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${this.apiUrl}/password-reset/request`, { email });
  }

  confirmPasswordReset(token: string, newPassword: string): Observable<void> {
    return this.http.post<void>(`${this.apiUrl}/password-reset/confirm`, { token, new_password: newPassword });
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
    // A troca encerra as sessões antigas no servidor (ADR-016): a resposta traz o token novo que
    // substitui o atual, para esta sessão seguir logada.
    return this.http.post<UserAccount & Partial<TokenResponse>>(`${this.apiUrl}/me/password`, {
      current_password: currentPassword,
      new_password: newPassword
    }).pipe(
      tap(({ access_token, token_type, ...user }) => {
        if (access_token) {
          localStorage.setItem(this.TOKEN_KEY, access_token);
        }
        this.currentUserSubject.next(user as UserAccount);
        try {
          localStorage.setItem(this.USER_KEY, JSON.stringify(user));
        } catch {
          // armazenamento indisponível: a sessão continua só em memória
        }
      }),
      map(({ access_token, token_type, ...user }) => user as UserAccount)
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
    
    // permissions are nested in roles; críticas vêm só da concessão individual
    const permissions = new Set<string>(user.critical_permissions ?? []);
    user.roles?.forEach(role => {
      role.permissions?.forEach((p: any) => permissions.add(p.code));
    });
    
    return permissions.has(requiredPermission);
  }
}
