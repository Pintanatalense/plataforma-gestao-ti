import { TestBed } from '@angular/core/testing';
import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { Location } from '@angular/common';
import { MatSnackBar } from '@angular/material/snack-bar';
import { AuthService } from '../auth/auth.service';
import { ErrorNotifier } from '../http/error-notifier.service';
import { jwtInterceptor } from './jwt.interceptor';

describe('jwtInterceptor', () => {
  let http: HttpClient;
  let backend: HttpTestingController;
  let auth: AuthService;
  let snack: { open: ReturnType<typeof vi.fn> };
  let logout: ReturnType<typeof vi.spyOn>;

  const fail = (url: string, status: number) => {
    http.get(url).subscribe({ error: () => {} });
    backend.expectOne(url).flush({}, { status, statusText: 'x' });
  };

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    snack = { open: vi.fn() };
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([jwtInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: MatSnackBar, useValue: snack }
      ]
    });
    http = TestBed.inject(HttpClient);
    backend = TestBed.inject(HttpTestingController);
    auth = TestBed.inject(AuthService);
    logout = vi.spyOn(auth, 'logout').mockImplementation(() => {});
    TestBed.inject(ErrorNotifier);
  });

  it('adds the bearer token when there is a session', () => {
    localStorage.setItem('access_token', 'tok');
    http.get('/api/v1/x').subscribe();
    const req = backend.expectOne('/api/v1/x');
    expect(req.request.headers.get('Authorization')).toBe('Bearer tok');
    req.flush({});
  });

  it('on 401 with a session: remembers the page, ends the session and tells the user', () => {
    localStorage.setItem('access_token', 'tok');
    const remember = vi.spyOn(auth, 'rememberReturnUrl');
    fail('/api/v1/assets', 401);
    expect(remember).toHaveBeenCalled();
    expect(logout).toHaveBeenCalledTimes(1);
    expect(snack.open.mock.calls[0][0]).toMatch(/sessão/i);
  });

  it('does not end the session on 401 from login/setup (wrong password is not an expired session)', () => {
    localStorage.setItem('access_token', 'tok');
    fail('/api/v1/identity/login', 401);
    expect(logout).not.toHaveBeenCalled();
    expect(snack.open).not.toHaveBeenCalled();
  });

  it('warns once, not once per request, when the server is unreachable (status 0)', () => {
    fail('/api/v1/a', 0);
    fail('/api/v1/b', 0);
    fail('/api/v1/c', 0);
    expect(snack.open).toHaveBeenCalledTimes(1);
    expect(snack.open.mock.calls[0][0]).toMatch(/Sem conexão/);
  });

  it('warns on 5xx', () => {
    fail('/api/v1/a', 500);
    expect(snack.open.mock.calls[0][0]).toMatch(/problema/);
  });

  it('stays silent for client errors, which each screen explains itself', () => {
    fail('/api/v1/a', 404);
    fail('/api/v1/b', 422);
    fail('/api/v1/c', 403);
    expect(snack.open).not.toHaveBeenCalled();
    expect(logout).not.toHaveBeenCalled();
  });

  it('still propagates the error to the caller', () => {
    let status = -1;
    http.get('/api/v1/a').subscribe({ error: (e) => (status = e.status) });
    backend.expectOne('/api/v1/a').flush({}, { status: 500, statusText: 'x' });
    expect(status).toBe(500);
  });

  it('still tells the user the session ended when a network notice came just before (no 5 s suppression)', () => {
    localStorage.setItem('access_token', 'tok');
    fail('/api/v1/a', 0); // aviso de rede
    fail('/api/v1/b', 401); // sessão caiu logo em seguida
    expect(logout).toHaveBeenCalledTimes(1);
    expect(snack.open).toHaveBeenCalledTimes(2);
    expect(snack.open.mock.calls[1][0]).toMatch(/sessão/i);
  });

  it('remembers the real browser address (a deep link opened with an expired token has router.url "/")', () => {
    localStorage.setItem('access_token', 'tok');
    vi.spyOn(TestBed.inject(Location), 'path').mockReturnValue('/assets/9?tab=x');
    const remember = vi.spyOn(auth, 'rememberReturnUrl');
    fail('/api/v1/assets/9', 401);
    expect(remember).toHaveBeenCalledWith('/assets/9?tab=x');
  });
});
