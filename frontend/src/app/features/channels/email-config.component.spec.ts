import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { MatSnackBar } from '@angular/material/snack-bar';
import { EmailConfigComponent } from './email-config.component';

const API = '/api/v1/notifications/email';
const URLS = { smtp: `${API}/config`, reset: `${API}/password-reset`, test: `${API}/test` };
const SAVED_SMTP = { is_enabled: true, host: 'smtp.real.local', port: 587, security: 'STARTTLS', username: 'u', password: '********', from_email: 'ti@real.local', from_name: 'x', app_base_url: 'https://ti.real.local' };

describe('Aba E-mail (movida do painel administrativo)', () => {
  let fixture: ComponentFixture<EmailConfigComponent>;
  let component: EmailConfigComponent;
  let backend: HttpTestingController;

  const fail = (url: string, status = 500) => backend.expectOne(url).flush({ error: { message: 'x' } }, { status, statusText: 'x' });
  const ok = (url: string, body: object) => backend.expectOne(url).flush(body);
  const settle = async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  };
  const load = async (smtp: object | null, reset: object | null) => {
    if (smtp) ok(URLS.smtp, smtp);
    else fail(URLS.smtp);
    if (reset) ok(URLS.reset, reset);
    else fail(URLS.reset);
    await settle();
  };
  const card = () => fixture.nativeElement.querySelector('[data-testid="password-reset-card"]') as HTMLElement;
  const toggle = () => fixture.nativeElement.querySelector('[data-testid="password-reset-toggle"]') as HTMLButtonElement;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [EmailConfigComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideNoopAnimations()]
    }).compileComponents();
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(EmailConfigComponent);
    component = fixture.componentInstance;
    (component as unknown as { snackBar: MatSnackBar }).snackBar = { open: vi.fn() } as unknown as MatSnackBar;
    fixture.detectChanges();
  });

  afterEach(() => vi.restoreAllMocks());

  describe('SMTP', () => {
    it('if the saved configuration cannot be read, the form (with code defaults) cannot be saved over it', async () => {
      await load(null, { enabled: false, smtp_ready: false });

      expect(component.smtpLoadError).toBeTruthy();
      component.saveSmtpConfig();
      backend.expectNone(URLS.smtp); // nenhum PUT foi enviado
      expect(component.savingSmtpConfig).toBe(false);
    });

    it('after a successful load, saving works', async () => {
      await load({ ...SAVED_SMTP, from_email: 'a@b.com' }, { enabled: false, smtp_ready: false });

      component.saveSmtpConfig();
      const put = backend.expectOne((r) => r.url === URLS.smtp && r.method === 'PUT');
      expect(put.request.body.host).toBe('smtp.real.local');
      put.flush({});
    });

    it('rejects a test without a valid destination and sends nothing', async () => {
      await load(SAVED_SMTP, { enabled: false, smtp_ready: false });
      component.testSmtpEmail = 'sem-arroba';
      component.runSmtpTest();
      backend.expectNone(URLS.test);
    });

    it('shows the server message when the test fails', async () => {
      await load(SAVED_SMTP, { enabled: false, smtp_ready: false });
      component.testSmtpEmail = 'a@b.com';
      component.runSmtpTest();
      backend.expectOne(URLS.test).flush({ error: { message: 'Falha de autenticação SMTP.' } }, { status: 400, statusText: 'x' });
      await settle();
      expect(component.smtpTestFeedback).toEqual({ success: false, message: 'Falha de autenticação SMTP.' });
    });
  });

  describe('Recuperação de senha por e-mail', () => {
    it('cannot be activated while the SMTP is not ready: button disabled and the reason is explained', async () => {
      await load(SAVED_SMTP, { enabled: false, smtp_ready: false });
      expect(toggle().disabled).toBe(true);
      expect(card().querySelector('[data-testid="password-reset-hint"]')).toBeTruthy();
    });

    it('activation asks for confirmation (server, sender, link address) and then calls the API', async () => {
      await load(SAVED_SMTP, { enabled: false, smtp_ready: true });
      const ask = vi.spyOn(window, 'confirm').mockReturnValue(true);
      toggle().click();
      // mostra o que está SALVO no servidor, não o que está no formulário
      backend.expectOne(URLS.smtp).flush({ ...SAVED_SMTP, host: 'smtp.salvo.local' });
      expect(ask.mock.calls[0][0]).toContain('smtp.salvo.local:587');
      expect(ask.mock.calls[0][0]).toContain('https://ti.real.local');
      const put = backend.expectOne((r) => r.url === URLS.reset && r.method === 'PUT');
      expect(put.request.body).toEqual({ enabled: true });
      put.flush({ enabled: true, smtp_ready: true });
      await settle();
      expect(card().textContent).toContain('Ativada');
    });

    it('declining the confirmation sends nothing', async () => {
      await load(SAVED_SMTP, { enabled: false, smtp_ready: true });
      vi.spyOn(window, 'confirm').mockReturnValue(false);
      toggle().click();
      backend.expectOne(URLS.smtp).flush(SAVED_SMTP);
      backend.expectNone((r) => r.url === URLS.reset && r.method === 'PUT');
    });

    it('a non-admin refused by the server gets the server message and the state does not change', async () => {
      await load(SAVED_SMTP, { enabled: false, smtp_ready: true });
      vi.spyOn(window, 'confirm').mockReturnValue(true);
      toggle().click();
      backend.expectOne(URLS.smtp).flush(SAVED_SMTP);
      backend
        .expectOne((r) => r.url === URLS.reset && r.method === 'PUT')
        .flush({ error: { message: 'Apenas administradores podem ativar a recuperação de senha.' } }, { status: 403, statusText: 'x' });
      await settle();
      expect(component.passwordReset?.enabled).toBe(false);
      expect(component.savingPasswordReset).toBe(false);
    });

    it('a failed read shows an error (never a state)', async () => {
      await load(SAVED_SMTP, null);
      expect(component.passwordResetError).toBeTruthy();
      expect(toggle()).toBeNull();
    });
  });
});
