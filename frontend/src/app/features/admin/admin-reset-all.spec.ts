import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { provideRouter } from '@angular/router';
import { MatSnackBar } from '@angular/material/snack-bar';
import { AdminComponent } from './admin.component';

const RESET_URL = '/api/v1/system/demo/reset-all';

describe('Painel administrativo: zerar toda a base', () => {
  let fixture: ComponentFixture<AdminComponent>;
  let component: AdminComponent;
  let backend: HttpTestingController;
  let snack: { open: ReturnType<typeof vi.fn> };

  const settle = async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
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
    snack = { open: vi.fn() };
    (component as unknown as { snackBar: MatSnackBar }).snackBar = snack as unknown as MatSnackBar;
    await settle();
    backend.match((r) => r.method === 'GET'); // cargas iniciais: não interessam aqui
  });

  it('frase errada não envia nada', () => {
    component.openResetAll();
    component.resetAllPhrase = 'zerar';
    component.executeResetAll();
    backend.expectNone(RESET_URL);
    expect(component.resettingAll).toBe(false);
  });

  it('frase certa (qualquer caixa) envia a frase, fecha o modal e recarrega o status', async () => {
    component.openResetAll();
    component.resetAllPhrase = ' zerar toda a base ';
    component.executeResetAll();

    const req = backend.expectOne(RESET_URL);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ confirmation_phrase: 'zerar toda a base' });
    req.flush({ success: true, message: 'Base zerada.', summary: {} });
    await settle();

    expect(component.showResetAllModal).toBe(false);
    expect(snack.open).toHaveBeenCalledWith('Base zerada.', 'OK', expect.anything());
    backend.expectOne('/api/v1/system/demo/status').flush({ system_mode: 'PRODUCTION' });
  });

  it('falha mostra a mensagem do servidor e mantém o modal aberto para tentar de novo', async () => {
    component.openResetAll();
    component.resetAllPhrase = 'ZERAR TODA A BASE';
    component.executeResetAll();
    backend.expectOne(RESET_URL).flush({ error: { message: 'Somente um administrador pode zerar a base.' } }, { status: 403, statusText: 'x' });
    await settle();

    expect(snack.open).toHaveBeenCalledWith('Somente um administrador pode zerar a base.', 'Fechar', expect.anything());
    expect(component.showResetAllModal).toBe(true);
    expect(component.resettingAll).toBe(false);
  });
});
