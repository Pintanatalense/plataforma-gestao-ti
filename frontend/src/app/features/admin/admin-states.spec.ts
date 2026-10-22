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
const URLS = {
  templates: `${API}/integrations/whatsapp/templates`,
  backups: `${API}/system/backups`,
  demo: `${API}/system/demo/status`,
  smtp: `${API}/notifications/email/config`
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
});
