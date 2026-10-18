import { TestBed } from '@angular/core/testing';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { provideRouter, Router } from '@angular/router';
import { of, throwError } from 'rxjs';
import { AuthService } from '../../core/auth/auth.service';
import { SetupComponent } from './setup.component';

async function mount(auth: object) {
  await TestBed.configureTestingModule({
    imports: [SetupComponent],
    providers: [provideRouter([]), provideAnimationsAsync(), { provide: AuthService, useValue: auth }]
  }).compileComponents();
  const fixture = TestBed.createComponent(SetupComponent);
  fixture.detectChanges();
  await fixture.whenStable();
  return fixture;
}

function fill(component: SetupComponent, extra: object = {}) {
  component.setupForm.patchValue({
    email: 'ti@empresa.com.br', password: 'senha-forte-1', confirmPassword: 'senha-forte-1', ...extra
  });
}

describe('SetupComponent', () => {
  it('starts on a clean base and explains both options', async () => {
    const fixture = await mount({ setupFirstAdmin: vi.fn() });
    const text = fixture.nativeElement.textContent;
    expect(fixture.componentInstance.isClean).toBe(true);
    expect(text).toContain('Base limpa');
    expect(text).toContain('Modelo de exemplo');
    expect(fixture.nativeElement.querySelector('[data-testid="company-name"]')).not.toBeNull();
  });

  it('requires the company name on a clean base but not on the example model', async () => {
    const fixture = await mount({ setupFirstAdmin: vi.fn() });
    const c = fixture.componentInstance;
    fill(c);
    expect(c.setupForm.invalid).toBe(true);

    c.setupForm.patchValue({ company_name: 'Acme Ltda' });
    expect(c.setupForm.valid).toBe(true);

    c.setupForm.patchValue({ company_name: '', setup_mode: 'DEMO' });
    fixture.detectChanges();
    expect(c.setupForm.valid).toBe(true);
    expect(fixture.nativeElement.querySelector('[data-testid="company-name"]')).toBeNull();
  });

  it('rejects mismatched passwords', async () => {
    const fixture = await mount({ setupFirstAdmin: vi.fn() });
    const c = fixture.componentInstance;
    fill(c, { company_name: 'Acme', confirmPassword: 'outra-senha-1' });
    expect(c.setupForm.hasError('mismatch')).toBe(true);
    expect(c.setupForm.invalid).toBe(true);
  });

  it('sends the company with the clean mode and goes to the dashboard', async () => {
    const auth = { setupFirstAdmin: vi.fn().mockReturnValue(of({})) };
    const fixture = await mount(auth);
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    const c = fixture.componentInstance;
    fill(c, { company_name: '  Acme Ltda ', company_cnpj: '' });
    c.onSubmit();

    expect(auth.setupFirstAdmin).toHaveBeenCalledWith({
      email: 'ti@empresa.com.br', password: 'senha-forte-1', setup_mode: 'CLEAN', company_name: 'Acme Ltda', company_cnpj: null
    });
    expect(navigate).toHaveBeenCalledWith(['/']);
  });

  it('sends no company data with the example model', async () => {
    const auth = { setupFirstAdmin: vi.fn().mockReturnValue(of({})) };
    const fixture = await mount(auth);
    vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    const c = fixture.componentInstance;
    fill(c, { setup_mode: 'DEMO', company_name: 'ignorado' });
    c.onSubmit();
    expect(auth.setupFirstAdmin).toHaveBeenCalledWith({ email: 'ti@empresa.com.br', password: 'senha-forte-1', setup_mode: 'DEMO' });
  });

  it('shows the server message and lets the user try again', async () => {
    const err = { error: { error: { message: 'A configuração inicial já foi concluída.' } } };
    const fixture = await mount({ setupFirstAdmin: vi.fn().mockReturnValue(throwError(() => err)) });
    const c = fixture.componentInstance;
    fill(c, { company_name: 'Acme' });
    c.onSubmit();
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('[data-testid="setup-error"]').textContent).toContain('já foi concluída');
    expect(c.isLoading).toBe(false);
  });
});
