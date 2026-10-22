import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { AuthService } from './auth.service';

describe('AuthService', () => {
  let service: AuthService;
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([])
      ]
    });
    service = TestBed.inject(AuthService);
    http = TestBed.inject(HttpTestingController);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('keeps the session after a password change by swapping in the token the server returns', () => {
    localStorage.setItem('access_token', 'old-token');
    let result: unknown;

    service.changeOwnPassword('atual', 'nova-senha-forte').subscribe((user) => (result = user));
    http.expectOne('/api/v1/identity/me/password').flush({
      id: 'u1',
      email: 'a@b.com',
      must_change_password: false,
      access_token: 'new-token',
      token_type: 'bearer'
    });

    expect(localStorage.getItem('access_token')).toBe('new-token');
    // o token não vaza para o usuário em memória nem para o cache local
    expect(result).toEqual({ id: 'u1', email: 'a@b.com', must_change_password: false });
    expect(localStorage.getItem('current_user')).not.toContain('new-token');
  });

  describe('return URL after a session ends', () => {
    beforeEach(() => sessionStorage.clear());

    it('remembers an internal page once and forgets it after reading', () => {
      service.rememberReturnUrl('/assets/123?tab=history');
      expect(service.takeReturnUrl()).toBe('/assets/123?tab=history');
      expect(service.takeReturnUrl()).toBeNull();
    });

    it.each(['//evil.example/x', 'https://evil.example', 'javascript:alert(1)', '/a b', '/x\\y', 'relativo', ''])(
      'refuses to remember %j (open redirect)',
      (url) => {
        service.rememberReturnUrl(url);
        expect(service.takeReturnUrl()).toBeNull();
      }
    );

    it('does not remember the login or setup pages', () => {
      service.rememberReturnUrl('/login');
      service.rememberReturnUrl('/setup');
      expect(service.takeReturnUrl()).toBeNull();
    });

    it('ignores a tampered value in storage', () => {
      sessionStorage.setItem('return_url', '//evil.example');
      expect(service.takeReturnUrl()).toBeNull();
    });
  });
});
