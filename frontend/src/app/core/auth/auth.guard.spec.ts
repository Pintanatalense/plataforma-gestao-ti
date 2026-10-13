import { TestBed } from '@angular/core/testing';
import { Router, UrlTree, provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { firstValueFrom, isObservable, of } from 'rxjs';
import { authGuard, guestGuard, permissionGuard } from './auth.guard';
import { AuthService, UserAccount } from './auth.service';

describe('Route guards', () => {
  let auth: AuthService;
  let router: Router;

  const run = async (guard: any, url = '/x') => {
    const result = TestBed.runInInjectionContext(() => guard({} as any, { url } as any));
    return isObservable(result) ? await firstValueFrom(result) : result;
  };

  const makeUser = (over: Partial<UserAccount> = {}): UserAccount => ({
    id: '1',
    email: 'a@b.c',
    must_change_password: false,
    is_admin: false,
    roles: [{ permissions: [{ code: 'assets.read' }] }],
    ...over
  });

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])]
    });
    auth = TestBed.inject(AuthService);
    router = TestBed.inject(Router);
  });

  it('authGuard redirects to /login without token', async () => {
    const res = (await run(authGuard)) as UrlTree;
    expect(router.serializeUrl(res)).toBe('/login');
  });

  it('authGuard forces password change when required', async () => {
    localStorage.setItem('access_token', 't');
    vi.spyOn(auth, 'ensureUser').mockReturnValue(of(makeUser({ must_change_password: true })));
    const res = (await run(authGuard, '/assets')) as UrlTree;
    expect(router.serializeUrl(res)).toBe('/change-password');
  });

  it('authGuard allows a valid session', async () => {
    localStorage.setItem('access_token', 't');
    vi.spyOn(auth, 'ensureUser').mockReturnValue(of(makeUser()));
    expect(await run(authGuard)).toBe(true);
  });

  it('permissionGuard allows user with permission', async () => {
    vi.spyOn(auth, 'ensureUser').mockReturnValue(of(makeUser()));
    vi.spyOn(auth, 'currentUserValue', 'get').mockReturnValue(makeUser());
    expect(await run(permissionGuard('assets.read'))).toBe(true);
  });

  it('permissionGuard blocks user without permission', async () => {
    vi.spyOn(auth, 'ensureUser').mockReturnValue(of(makeUser()));
    vi.spyOn(auth, 'currentUserValue', 'get').mockReturnValue(makeUser());
    const res = (await run(permissionGuard('identity.users.read'))) as UrlTree;
    expect(router.serializeUrl(res)).toBe('/dashboard');
  });

  it('permissionGuard allows admin for any permission', async () => {
    const admin = makeUser({ is_admin: true, roles: [] });
    vi.spyOn(auth, 'ensureUser').mockReturnValue(of(admin));
    vi.spyOn(auth, 'currentUserValue', 'get').mockReturnValue(admin);
    expect(await run(permissionGuard('identity.users.read'))).toBe(true);
  });

  it('guestGuard sends logged users to dashboard', async () => {
    localStorage.setItem('access_token', 't');
    const res = (await run(guestGuard)) as UrlTree;
    expect(router.serializeUrl(res)).toBe('/dashboard');
  });
});
