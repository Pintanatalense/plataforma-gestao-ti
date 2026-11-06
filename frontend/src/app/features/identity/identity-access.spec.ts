import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { AuthService } from '../../core/auth/auth.service';
import { RoleDialogComponent } from './role-list/role-dialog.component';
import { UserAccessDialogComponent } from './user-list/user-access-dialog.component';

const PERMS = [
  { id: 'p1', code: 'assets.read', description: 'Ler ativos', label: 'Ver patrimônio', module: 'assets', module_label: 'Patrimônio e ativos', risk: 'leitura', risk_label: 'Leitura', is_critical: false },
  { id: 'p2', code: 'assets.write', description: 'Editar ativos', label: 'Cadastrar e editar ativos', module: 'assets', module_label: 'Patrimônio e ativos', risk: 'alteracao', risk_label: 'Alteração', is_critical: false },
  { id: 'p3', code: 'audit.read', description: 'Ver auditoria', label: 'Ver auditoria', module: 'audit', module_label: 'Auditoria', risk: 'leitura', risk_label: 'Leitura', is_critical: false },
  { id: 'p4', code: 'system.backup.download', description: 'Baixar', label: 'Baixar backups', module: 'system', module_label: 'Sistema, dados e backups', risk: 'execucao', risk_label: 'Execução', is_critical: true },
];

const el = (root: HTMLElement, id: string) => root.querySelector(`[data-testid="${id}"]`) as HTMLElement | null;

describe('Editor de perfis: permissões agrupadas por módulo, em português, com risco', () => {
  async function mount(role: unknown = null) {
    const close = vi.fn();
    await TestBed.configureTestingModule({
      imports: [RoleDialogComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideAnimationsAsync(),
        { provide: MAT_DIALOG_DATA, useValue: role },
        { provide: MatDialogRef, useValue: { close } },
      ],
    }).compileComponents();
    const fixture = TestBed.createComponent(RoleDialogComponent);
    fixture.detectChanges();
    return { fixture, close, http: TestBed.inject(HttpTestingController) };
  }

  it('agrupa por módulo, mostra rótulo e risco, e deixa as críticas de fora', async () => {
    const { fixture, http } = await mount();
    http.expectOne('/api/v1/identity/permissions').flush(PERMS);
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    expect(el(root, 'module-assets')!.textContent).toContain('Patrimônio e ativos');
    expect(el(root, 'module-assets')!.textContent).toContain('Cadastrar e editar ativos');
    expect(el(root, 'module-assets')!.textContent).toContain('Alteração');
    expect(el(root, 'module-audit')).not.toBeNull();
    expect(el(root, 'module-system')).toBeNull(); // só crítica nesse módulo
    expect(root.textContent).not.toContain('Baixar backups');
  });

  it('salva as permissões marcadas, mantendo as que o perfil já tinha', async () => {
    const { fixture, http, close } = await mount({ id: 'r1', name: 'Ativos', description: '', permissions: [PERMS[0]] });
    http.expectOne('/api/v1/identity/permissions').flush(PERMS);
    fixture.detectChanges();
    const comp = fixture.componentInstance;
    comp.toggle('p3', true);
    comp.save();
    expect(close).toHaveBeenCalledWith({ name: 'Ativos', description: '', permission_ids: ['p1', 'p3'] });
  });

  it('se a lista de permissões não carrega, avisa e não deixa salvar (salvar apagaria as do perfil)', async () => {
    const { fixture, http, close } = await mount({ id: 'r1', name: 'Ativos', description: '', permissions: [PERMS[0]] });
    http.expectOne('/api/v1/identity/permissions').flush({ error: { message: 'Falhou.' } }, { status: 500, statusText: 'x' });
    fixture.detectChanges();
    expect(el(fixture.nativeElement, 'permissions-error')).not.toBeNull();
    fixture.componentInstance.save();
    expect(close).not.toHaveBeenCalled();
  });
});

describe('Acesso do usuário: acesso efetivo e permissões críticas', () => {
  const USER = { id: 'u1', email: 'ana@empresa.com.br', roles: [], is_admin: false, is_active: true };
  const EFFECTIVE = [
    { ...PERMS[0], sources: ['Perfil Atendente'] },
    { ...PERMS[3], sources: ['Concessão individual'] },
  ];
  const GRANT = { permission: 'system.backup.download', label: 'Baixar backups', granted_via: 'api', granted_at: '2026-10-25T10:00:00Z', reason: 'plantão' };

  async function mount(canGrant: boolean) {
    await TestBed.configureTestingModule({
      imports: [UserAccessDialogComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideAnimationsAsync(),
        { provide: MAT_DIALOG_DATA, useValue: USER },
        { provide: AuthService, useValue: { hasPermission: (p: string) => canGrant && p === 'identity.critical.grant' } },
      ],
    }).compileComponents();
    const fixture = TestBed.createComponent(UserAccessDialogComponent);
    fixture.detectChanges();
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/api/v1/identity/users/u1/effective-access').flush(EFFECTIVE);
    http.expectOne('/api/v1/identity/users/u1/critical-permissions').flush([GRANT]);
    return { fixture, http };
  }

  it('mostra cada permissão com a origem, agrupada por módulo', async () => {
    const { fixture } = await mount(false);
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    expect(el(root, 'effective-assets')!.textContent).toContain('Ver patrimônio');
    expect(el(root, 'effective-assets')!.textContent).toContain('Perfil Atendente');
    expect(el(root, 'grant-system.backup.download')!.textContent).toContain('plantão');
  });

  it('sem a permissão de conceder críticas: nada de conceder nem revogar', async () => {
    const { fixture, http } = await mount(false);
    fixture.detectChanges();
    http.expectNone('/api/v1/identity/permissions');
    expect(el(fixture.nativeElement, 'grant-select')).toBeNull();
    expect(fixture.nativeElement.textContent).not.toContain('Revogar');
  });

  it('com a permissão: concede com motivo e recarrega', async () => {
    const { fixture, http } = await mount(true);
    http.expectOne('/api/v1/identity/permissions').flush(PERMS.concat({ ...PERMS[3], id: 'p5', code: 'system.data.import', label: 'Importar dados' }));
    fixture.detectChanges();
    const comp = fixture.componentInstance;
    expect(comp.grantable().map((p) => p.code)).toEqual(['system.data.import']); // a já concedida não aparece
    comp.newPermission = 'system.data.import';
    comp.reason = 'migração de dados';
    comp.grant();
    const req = http.expectOne('/api/v1/identity/users/u1/critical-permissions');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ permission: 'system.data.import', reason: 'migração de dados' });
    req.flush([GRANT]);
    http.expectOne('/api/v1/identity/users/u1/effective-access').flush(EFFECTIVE);
    http.expectOne('/api/v1/identity/users/u1/critical-permissions').flush([GRANT]);
    expect(comp.error()).toBeNull();
  });

  it('mostra a mensagem do servidor quando a concessão é recusada', async () => {
    const { fixture, http } = await mount(true);
    http.expectOne('/api/v1/identity/permissions').flush(PERMS);
    const comp = fixture.componentInstance;
    comp.newPermission = 'system.backup.download';
    comp.reason = 'para mim mesmo';
    comp.grant();
    http
      .expectOne('/api/v1/identity/users/u1/critical-permissions')
      .flush({ error: { message: 'Ninguém concede permissão crítica a si mesmo.' } }, { status: 403, statusText: 'x' });
    fixture.detectChanges();
    expect(el(fixture.nativeElement, 'access-error')!.textContent).toContain('si mesmo');
  });
});
