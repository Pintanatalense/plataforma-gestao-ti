import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ChangePasswordComponent } from './change-password/change-password.component';
import { StockCreateComponent } from '../stock/stock-create/stock-create.component';

/**
 * O backend responde `{error: {message}}` (nunca `detail`): as telas devem mostrar a mensagem real do servidor
 * (ex.: "Senha atual incorreta."), não a genérica de reserva.
 */
async function setup<T>(component: new () => T) {
  await TestBed.configureTestingModule({
    imports: [component],
    providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([]), provideNoopAnimations()]
  }).compileComponents();
  const backend = TestBed.inject(HttpTestingController);
  vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
  const fixture = TestBed.createComponent(component);
  const snack = { open: vi.fn() };
  (fixture.componentInstance as unknown as { snackBar: MatSnackBar }).snackBar = snack as unknown as MatSnackBar;
  fixture.detectChanges();
  const settle = async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  };
  return { backend, fixture, snack, settle, el: fixture.nativeElement as HTMLElement };
}

describe('Mensagens reais do servidor nas telas restantes', () => {
  it('troca de senha: mostra "Senha atual incorreta." e libera o botão (não fica carregando)', async () => {
    const { backend, fixture, snack, settle, el } = await setup(ChangePasswordComponent);
    const c = fixture.componentInstance;
    c.form.patchValue({ currentPassword: 'errada-123', newPassword: 'nova-senha-1', confirmPassword: 'nova-senha-1' });
    c.onSubmit();
    await settle();
    expect(el.querySelector('mat-spinner')).toBeTruthy(); // enviando
    backend
      .expectOne('/api/v1/identity/me/password')
      .flush({ error: { message: 'Senha atual incorreta.' } }, { status: 400, statusText: 'x' });
    await settle();
    expect(snack.open.mock.calls[0][0]).toBe('Senha atual incorreta.');
    expect(el.querySelector('mat-spinner')).toBeNull(); // o botão voltou ao normal
  });

  it('novo item de estoque: mostra a mensagem do servidor em vez da genérica', async () => {
    const { backend, fixture, snack } = await setup(StockCreateComponent);
    backend.match(() => true); // unidades e categorias do ngOnInit
    const c = fixture.componentInstance;
    c.form.patchValue({ name: 'Cabo', unit_id: 'u1', initial_quantity: 1, min_quantity: 0 } as never);
    c.onSubmit();
    backend
      .expectOne((r) => r.method === 'POST' && r.url.startsWith('/api/v1/stock'))
      .flush({ error: { message: 'Já existe um item com esse nome.' } }, { status: 409, statusText: 'x' });
    expect(snack.open.mock.calls[0][0]).toBe('Já existe um item com esse nome.');
  });
});
