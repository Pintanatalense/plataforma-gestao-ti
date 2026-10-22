import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { provideRouter } from '@angular/router';
import { MatSnackBar } from '@angular/material/snack-bar';
import { AdminComponent } from './admin.component';

const API = '/api/v1';
/** Posição da aba "Backups do Banco de Dados" no painel. */
const BACKUPS_TAB = 3;
/** Posição da aba de e-mail/SMTP. */
const SMTP_TAB = 6;
const SAVED_SMTP = { is_enabled: true, host: 'smtp.real.local', port: 587, security: 'STARTTLS', username: 'u', password: '********', from_email: 'ti@real.local', from_name: 'x', app_base_url: 'https://ti.real.local' };
const URLS = {
  templates: `${API}/integrations/whatsapp/templates`,
  backups: `${API}/system/backups`,
  demo: `${API}/system/demo/status`,
  smtp: `${API}/notifications/email/config`,
  reset: `${API}/notifications/email/password-reset`
};

describe('Painel administrativo: falhas de carga não parecem "vazio" nem permitem salvar por cima', () => {
  let fixture: ComponentFixture<AdminComponent>;
  let component: AdminComponent;
  let backend: HttpTestingController;

  const fail = (url: string, status = 500) => backend.expectOne(url).flush({ error: { message: 'x' } }, { status, statusText: 'x' });
  const ok = (url: string, body: object) => backend.expectOne(url).flush(body);
  const settle = async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  };
  /** O painel é OnPush: alterar a aba por código exige marcar para verificação. */
  const openTab = async (index: number) => {
    component.activeTabIndex = index;
    (component as unknown as { cdr: { markForCheck(): void } }).cdr.markForCheck();
    await settle();
    await settle();
  };

  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({
      imports: [AdminComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideNoopAnimations(), provideRouter([])]
    }).compileComponents();
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(AdminComponent);
    component = fixture.componentInstance;
    // o componente importa MatSnackBarModule: espiona a instância dele
    (component as unknown as { snackBar: MatSnackBar }).snackBar = { open: vi.fn() } as unknown as MatSnackBar;
    await settle();
  });

  it('SMTP: if the saved configuration cannot be read, the form (with code defaults) cannot be saved over it', async () => {
    ok(URLS.templates, []);
    ok(URLS.backups, []);
    ok(URLS.demo, { system_mode: 'PRODUCTION' });
    fail(URLS.smtp);
    await settle();

    expect(component.smtpLoadError).toBeTruthy();
    component.saveSmtpConfig();
    backend.expectNone(URLS.smtp); // nenhum PUT foi enviado
    expect(component.savingSmtpConfig).toBe(false);
  });

  it('SMTP: after a successful load, saving works', async () => {
    ok(URLS.templates, []);
    ok(URLS.backups, []);
    ok(URLS.demo, { system_mode: 'PRODUCTION' });
    ok(URLS.smtp, { is_enabled: true, host: 'smtp.real.local', port: 587, security: 'STARTTLS', username: 'u', password: '********', from_email: 'a@b.com', from_name: 'x', app_base_url: 'https://ti' });
    await settle();

    component.saveSmtpConfig();
    const put = backend.expectOne((r) => r.url === URLS.smtp && r.method === 'PUT');
    expect(put.request.body.host).toBe('smtp.real.local');
    put.flush({});
  });

  it('Backups: a failed list is an error with retry, never "Nenhum backup gerado"', async () => {
    ok(URLS.templates, []);
    fail(URLS.backups);
    ok(URLS.demo, { system_mode: 'PRODUCTION' });
    ok(URLS.smtp, { is_enabled: false });
    await settle();
    await openTab(BACKUPS_TAB); // as abas só renderizam quando ativas

    expect(component.backupsError).toBeTruthy();
    expect(fixture.nativeElement.querySelector('[data-testid="state-error"]')).toBeTruthy();
    const text = fixture.nativeElement.textContent as string;
    expect(text).not.toContain('Nenhum backup gerado');
  });

  it('Backups: the checksum comes from checksum_sha256 (the API field) and can be verified', async () => {
    ok(URLS.templates, []);
    ok(URLS.backups, [
      { id: 'b1', filename: 'backup_1.sql.gz', size_bytes: 1000, checksum_sha256: 'abcdef0123456789abcdef', status: 'SUCCESS', error_message: null, created_at: '2026-01-01T00:00:00Z', created_by_email: null }
    ]);
    ok(URLS.demo, { system_mode: 'PRODUCTION' });
    ok(URLS.smtp, { is_enabled: false });
    await settle();
    await openTab(BACKUPS_TAB);

    expect(fixture.nativeElement.textContent).toContain('abcdef0123456789'); // antes: sempre "N/A"

    component.verifyBackup(component.backups[0]);
    backend.expectOne(`${URLS.backups}/b1/verify`).flush({ backup_id: 'b1', filename: 'backup_1.sql.gz', exists: true, is_valid: false });
    await settle();
    expect(component.backupVerification['b1'].valid).toBe(false);
    expect(component.backupVerification['b1'].message).toMatch(/NÃO confere/);
  });

  it('Modelos de mensagem: a failed list is not shown as "nenhum modelo"', async () => {
    fail(URLS.templates);
    ok(URLS.backups, []);
    ok(URLS.demo, { system_mode: 'PRODUCTION' });
    ok(URLS.smtp, { is_enabled: false });
    await settle();
    expect(component.templatesError).toBeTruthy();
  });

  describe('Recuperação de senha por e-mail', () => {
    const load = async (reset: object | null) => {
      ok(URLS.templates, []);
      ok(URLS.backups, []);
      ok(URLS.demo, { system_mode: 'PRODUCTION' });
      ok(URLS.smtp, { is_enabled: true, host: 'smtp.real.local', port: 587, security: 'STARTTLS', username: 'u', password: '********', from_email: 'ti@real.local', from_name: 'x', app_base_url: 'https://ti.real.local' });
      if (reset) ok(URLS.reset, reset);
      else fail(URLS.reset);
      await settle();
      await openTab(SMTP_TAB);
    };
    const card = () => fixture.nativeElement.querySelector('[data-testid="password-reset-card"]') as HTMLElement;
    const toggle = () => fixture.nativeElement.querySelector('[data-testid="password-reset-toggle"]') as HTMLButtonElement;

    it('cannot be activated while the SMTP is not ready: button disabled and the reason is explained', async () => {
      await load({ enabled: false, smtp_ready: false });
      expect(toggle().disabled).toBe(true);
      expect(card().querySelector('[data-testid="password-reset-hint"]')).toBeTruthy();
    });

    it('activation asks for confirmation (server, sender, link address) and then calls the API', async () => {
      await load({ enabled: false, smtp_ready: true });
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
      ask.mockRestore();
    });

    it('declining the confirmation sends nothing', async () => {
      await load({ enabled: false, smtp_ready: true });
      const ask = vi.spyOn(window, 'confirm').mockReturnValue(false);
      toggle().click();
      backend.expectOne(URLS.smtp).flush(SAVED_SMTP);
      backend.expectNone((r) => r.url === URLS.reset && r.method === 'PUT');
      ask.mockRestore();
    });

    it('a non-admin refused by the server gets the server message and the state does not change', async () => {
      await load({ enabled: false, smtp_ready: true });
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
      await load(null);
      expect(component.passwordResetError).toBeTruthy();
      expect(toggle()).toBeNull();
    });
  });
});
