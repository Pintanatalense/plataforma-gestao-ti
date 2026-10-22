import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { MatSnackBar } from '@angular/material/snack-bar';
import { AuthService } from '../../../core/auth/auth.service';
import { OrganizationService } from '../../../core/services/organization.service';
import { CompanyComponent } from './company.component';

const URL = '/api/v1/organization/company';
const COMPANY = { id: 'c1', name: 'Acme', cnpj: '00.000.000/0001-00', logo_url: null };

describe('Tela da empresa', () => {
  let fixture: ComponentFixture<CompanyComponent>;
  let component: CompanyComponent;
  let backend: HttpTestingController;
  let org: OrganizationService;
  let snack: { open: ReturnType<typeof vi.fn> };

  const settle = async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  };
  const create = async (canEdit: boolean) => {
    await TestBed.configureTestingModule({
      imports: [CompanyComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideNoopAnimations(),
        { provide: AuthService, useValue: { hasPermission: (p: string) => canEdit || p.endsWith('.read') } }
      ]
    }).compileComponents();
    backend = TestBed.inject(HttpTestingController);
    org = TestBed.inject(OrganizationService);
    fixture = TestBed.createComponent(CompanyComponent);
    component = fixture.componentInstance;
    snack = { open: vi.fn() };
    (component as unknown as { snackBar: MatSnackBar }).snackBar = snack as unknown as MatSnackBar;
    await settle();
  };
  const exact = (method: string) => (r: { url: string; method: string }) => r.url === URL && r.method === method;

  it('load failure shows the server message with retry, never an empty form', async () => {
    await create(true);
    backend.expectOne(exact('GET')).flush({ error: { message: 'Empresa não cadastrada.' } }, { status: 404, statusText: 'x' });
    await settle();
    expect(fixture.nativeElement.querySelector('[data-testid="state-error"]')).toBeTruthy();
    expect(fixture.nativeElement.textContent).toContain('Empresa não cadastrada.');
    expect(fixture.nativeElement.querySelector('form')).toBeNull();
  });

  it('saving sends name/cnpj and updates the shared branding (menu and login)', async () => {
    await create(true);
    backend.expectOne(exact('GET')).flush(COMPANY);
    await settle();

    component.form.patchValue({ name: ' Nova Acme ', cnpj: '' });
    component.save();
    const patch = backend.expectOne(exact('PATCH'));
    expect(patch.request.body).toEqual({ name: 'Nova Acme', cnpj: null });
    patch.flush({ ...COMPANY, name: 'Nova Acme', cnpj: null });
    await settle();

    expect(org.branding$.value).toEqual({ name: 'Nova Acme', logo_url: null });
    expect(snack.open).toHaveBeenCalledWith('Dados da empresa salvos.', 'Fechar', expect.anything());
  });

  it('a failed save keeps the form and shows the server message', async () => {
    await create(true);
    backend.expectOne(exact('GET')).flush(COMPANY);
    await settle();
    component.form.patchValue({ name: 'X' });
    component.save();
    backend.expectOne(exact('PATCH')).flush({ error: { message: 'Nome inválido.' } }, { status: 422, statusText: 'x' });
    await settle();
    expect(snack.open.mock.calls[0][0]).toContain('Nome inválido.');
    expect(component.saving).toBe(false);
    expect(org.branding$.value).toBeNull();
  });

  it('rejects a wrong file type or size before sending anything', async () => {
    await create(true);
    backend.expectOne(exact('GET')).flush(COMPANY);
    await settle();
    const pick = (file: File) => component.onLogoSelected({ target: { files: [file], value: '' } } as unknown as Event);

    pick(new File(['x'], 'a.svg', { type: 'image/svg+xml' }));
    pick(new File([new Uint8Array(2 * 1024 * 1024 + 1)], 'big.png', { type: 'image/png' }));
    backend.expectNone(`${URL}/logo`);
    expect(snack.open).toHaveBeenCalledTimes(2);
  });

  it('uploads a valid logo and publishes the new branding', async () => {
    await create(true);
    backend.expectOne(exact('GET')).flush(COMPANY);
    await settle();
    component.onLogoSelected({ target: { files: [new File(['x'], 'l.png', { type: 'image/png' })], value: '' } } as unknown as Event);
    backend.expectOne(`${URL}/logo`).flush({ logo_url: '/static/logo.png?v=1', message: 'ok' });
    await settle();
    expect(org.branding$.value).toEqual({ name: 'Acme', logo_url: '/static/logo.png?v=1' });
    expect(fixture.nativeElement.querySelector('[data-testid="company-logo"]')).toBeTruthy();
  });

  it('without update permission the form is read-only and has no save/upload buttons', async () => {
    await create(false);
    backend.expectOne(exact('GET')).flush(COMPANY);
    await settle();
    expect(fixture.nativeElement.querySelector('[data-testid="company-save"]')).toBeNull();
    expect(fixture.nativeElement.querySelector('[data-testid="logo-pick"]')).toBeNull();
    expect(component.form.disabled).toBe(true);
  });
});
