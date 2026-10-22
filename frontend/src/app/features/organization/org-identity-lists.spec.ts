import { Type } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { MatSnackBar } from '@angular/material/snack-bar';
import { UnitList } from './unit-list/unit-list.component';
import { SectorList } from './sector-list/sector-list.component';
import { EmployeeList } from './employee-list/employee-list.component';
import { RoleList } from '../identity/role-list/role-list.component';
import { UserList } from '../identity/user-list/user-list.component';
import { generateTemporaryPassword } from '../../core/auth/temporary-password';

const SCREENS: { name: string; cmp: Type<unknown>; url: string; emptyText: string }[] = [
  { name: 'Unidades', cmp: UnitList, url: '/api/v1/organization/units', emptyText: 'Nenhuma unidade' },
  { name: 'Setores', cmp: SectorList, url: '/api/v1/organization/sectors', emptyText: 'Nenhum setor' },
  { name: 'Colaboradores', cmp: EmployeeList, url: '/api/v1/organization/employees', emptyText: 'Nenhum colaborador' },
  { name: 'Perfis', cmp: RoleList, url: '/api/v1/identity/roles', emptyText: 'Nenhum perfil' },
  { name: 'Usuários', cmp: UserList, url: '/api/v1/identity/users', emptyText: 'Nenhum usuário' }
];

describe.each(SCREENS)('Organização/Identidade — $name: falha de API não parece lista vazia', ({ cmp, url, emptyText }) => {
  let fixture: ComponentFixture<any>;
  let backend: HttpTestingController;
  const match = (r: { url: string }) => r.url.startsWith(url);
  const settle = async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  };
  const text = () => fixture.nativeElement.textContent as string;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [cmp],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideNoopAnimations()]
    }).compileComponents();
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(cmp);
    fixture.componentInstance.snackBar = { open: vi.fn() } as unknown as MatSnackBar;
    await settle();
  });

  it('mostra o erro do servidor com "Tentar novamente" (nunca o texto de vazio)', async () => {
    backend.expectOne(match).flush({ error: { message: 'Sem permissão para listar.' } }, { status: 403, statusText: 'x' });
    await settle();
    expect(fixture.nativeElement.querySelector('[data-testid="state-error"]')).toBeTruthy();
    expect(text()).toContain('Sem permissão para listar.');
    expect(text()).not.toContain(emptyText);
    expect(fixture.nativeElement.querySelector('table')).toBeNull();
  });

  it('"Tentar novamente" refaz a chamada e mostra o estado vazio quando a lista realmente é vazia', async () => {
    backend.expectOne(match).flush({}, { status: 500, statusText: 'x' });
    await settle();
    (fixture.nativeElement.querySelector('[data-testid="state-retry"]') as HTMLButtonElement).click();
    backend.expectOne(match).flush([]);
    await settle();
    expect(fixture.nativeElement.querySelector('[data-testid="state-error"]')).toBeNull();
    expect(text()).toContain(emptyText);
  });

  it('recarga que falha depois de carregar mantém a tela e só avisa', async () => {
    backend.expectOne(match).flush([{ id: '1', name: 'A', code: 'A', email: 'a@b.com', roles: [], is_active: true }]);
    await settle();
    fixture.componentInstance.loadData();
    backend.expectOne(match).flush({}, { status: 500, statusText: 'x' });
    await settle();
    expect(fixture.componentInstance.loadError).toBeNull();
    expect(fixture.nativeElement.querySelector('table')).toBeTruthy();
    expect(fixture.componentInstance.snackBar.open).toHaveBeenCalled();
  });
});

describe('Senha temporária', () => {
  it('é aleatória, com 16 caracteres, e nunca a antiga senha fixa', () => {
    const a = generateTemporaryPassword();
    const b = generateTemporaryPassword();
    expect(a).toHaveLength(16);
    expect(a).not.toBe(b);
    expect(a).not.toBe('temporaria-123');
  });
});
