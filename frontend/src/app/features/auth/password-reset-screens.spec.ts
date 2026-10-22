import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { ForgotPasswordComponent } from './forgot-password/forgot-password.component';
import { LoginComponent } from './login/login.component';
import { ResetPasswordComponent } from './reset-password/reset-password.component';

const ID = '/api/v1/identity';
const q = (el: HTMLElement, id: string) => el.querySelector(`[data-testid="${id}"]`) as HTMLElement | null;

async function setup<T>(component: new () => T, token: string | null = null) {
  await TestBed.configureTestingModule({
    imports: [component],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([]),
      provideNoopAnimations(),
      { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: convertToParamMap(token ? { token } : {}) } } }
    ]
  }).compileComponents();
  const backend = TestBed.inject(HttpTestingController);
  const router = TestBed.inject(Router);
  const nav = vi.spyOn(router, 'navigate').mockResolvedValue(true);
  const fixture = TestBed.createComponent(component);
  const settle = async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  };
  fixture.detectChanges();
  return { backend, fixture, nav, settle, el: fixture.nativeElement as HTMLElement };
}

describe('Login: link "Esqueci minha senha"', () => {
  it.each([
    [true, true],
    [false, false]
  ])('status enabled=%s → link visible=%s', async (enabled, visible) => {
    const { backend, settle, el } = await setup(LoginComponent);
    backend.match((r) => r.url.includes('/setup/status'));
    backend.match((r) => r.url.includes('/company/public'));
    backend.expectOne(`${ID}/password-reset/status`).flush({ enabled });
    await settle();
    expect(!!q(el, 'forgot-link')).toBe(visible);
  });

  it('no link when the status call fails (login keeps working)', async () => {
    const { backend, settle, el } = await setup(LoginComponent);
    backend.match((r) => r.url.includes('/setup/status'));
    backend.match((r) => r.url.includes('/company/public'));
    backend.expectOne(`${ID}/password-reset/status`).flush({}, { status: 500, statusText: 'x' });
    await settle();
    expect(q(el, 'forgot-link')).toBeNull();
  });
});

describe('Esqueci minha senha', () => {
  it('disabled: shows it is unavailable and offers no form', async () => {
    const { backend, settle, el } = await setup(ForgotPasswordComponent);
    backend.expectOne(`${ID}/password-reset/status`).flush({ enabled: false });
    await settle();
    expect(q(el, 'reset-unavailable')).toBeTruthy();
    expect(q(el, 'reset-submit')).toBeNull();
  });

  it('sends the e-mail and shows the same generic message, whatever the account', async () => {
    const { backend, fixture, settle, el } = await setup(ForgotPasswordComponent);
    backend.expectOne(`${ID}/password-reset/status`).flush({ enabled: true });
    await settle();
    fixture.componentInstance.form.patchValue({ email: 'ana@empresa.com' });
    fixture.componentInstance.submit();
    const req = backend.expectOne(`${ID}/password-reset/request`);
    expect(req.request.body).toEqual({ email: 'ana@empresa.com' });
    req.flush({ message: 'Se o e-mail estiver cadastrado, enviaremos um link.' }, { status: 202, statusText: 'Accepted' });
    await settle();
    expect(q(el, 'reset-sent')?.textContent).toContain('Se o e-mail estiver cadastrado');
  });

  it('a failed request shows the error and lets the user try again', async () => {
    const { backend, fixture, settle, el } = await setup(ForgotPasswordComponent);
    backend.expectOne(`${ID}/password-reset/status`).flush({ enabled: true });
    await settle();
    fixture.componentInstance.form.patchValue({ email: 'ana@empresa.com' });
    fixture.componentInstance.submit();
    backend.expectOne(`${ID}/password-reset/request`).flush({ error: { message: 'Recuperação indisponível.' } }, { status: 404, statusText: 'x' });
    await settle();
    expect(q(el, 'reset-error')?.textContent).toContain('Recuperação indisponível.');
    expect(q(el, 'reset-submit')).toBeTruthy();
  });
});

describe('Redefinir senha', () => {
  const TOKEN = 't'.repeat(43);

  it('takes the token out of the address bar and keeps it only in memory', async () => {
    const { nav, fixture } = await setup(ResetPasswordComponent, TOKEN);
    expect(fixture.componentInstance.token).toBe(TOKEN);
    expect(nav).toHaveBeenCalledWith([], expect.objectContaining({ queryParams: { token: null }, replaceUrl: true }));
  });

  it('without a token: invalid-link message and a way to ask for a new one', async () => {
    const { el } = await setup(ResetPasswordComponent, null);
    expect(q(el, 'reset-no-token')).toBeTruthy();
    expect(q(el, 'reset-submit')).toBeNull();
  });

  it('refuses short or mismatching passwords before calling the API', async () => {
    const { backend, fixture, settle, el } = await setup(ResetPasswordComponent, TOKEN);
    fixture.componentInstance.form.patchValue({ password: 'curta', confirm: 'curta' });
    expect(fixture.componentInstance.form.invalid).toBe(true);
    fixture.componentInstance.form.patchValue({ password: 'senha-longa-1', confirm: 'senha-longa-2' });
    fixture.componentInstance.form.controls.confirm.markAsDirty();
    await settle();
    expect(q(el, 'reset-mismatch')).toBeTruthy();
    fixture.componentInstance.submit();
    backend.expectNone(`${ID}/password-reset/confirm`);
  });

  it('confirms, shows success and forgets the token', async () => {
    const { backend, fixture, settle, el } = await setup(ResetPasswordComponent, TOKEN);
    fixture.componentInstance.form.patchValue({ password: 'senha-longa-1', confirm: 'senha-longa-1' });
    fixture.componentInstance.submit();
    const req = backend.expectOne(`${ID}/password-reset/confirm`);
    expect(req.request.body).toEqual({ token: TOKEN, new_password: 'senha-longa-1' });
    req.flush(null, { status: 204, statusText: 'No Content' });
    await settle();
    expect(q(el, 'reset-done')).toBeTruthy();
    expect(fixture.componentInstance.token).toBeNull();
  });

  it('an expired/used link shows the server message and keeps the form', async () => {
    const { backend, fixture, settle, el } = await setup(ResetPasswordComponent, TOKEN);
    fixture.componentInstance.form.patchValue({ password: 'senha-longa-1', confirm: 'senha-longa-1' });
    fixture.componentInstance.submit();
    backend.expectOne(`${ID}/password-reset/confirm`).flush(
      { error: { message: 'Link inválido ou expirado. Peça um novo link de recuperação.' } },
      { status: 422, statusText: 'x' }
    );
    await settle();
    expect(q(el, 'reset-error')?.textContent).toContain('Link inválido ou expirado');
    expect(q(el, 'reset-done')).toBeNull();
  });
});
