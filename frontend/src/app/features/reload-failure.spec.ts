import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { MatSnackBar } from '@angular/material/snack-bar';
import { of } from 'rxjs';

import { StockDetailComponent } from './stock/stock-detail/stock-detail.component';

/**
 * Recarga depois de uma ação já confirmada (ex.: movimentação registrada): se a recarga falhar, a tela que o usuário
 * já tem continua lá e só aparece um aviso. Trocar tudo por um erro de tela cheia apagaria o contexto de uma
 * operação que deu certo.
 */
describe('Detalhe de estoque: falha na recarga', () => {
  let fixture: ComponentFixture<StockDetailComponent>;
  let backend: HttpTestingController;
  let snack: { open: ReturnType<typeof vi.fn> };

  const item = {
    id: '1',
    name: 'Cabo HDMI',
    unit_id: 'u1',
    quantity: 10,
    min_quantity: 2,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z'
  };

  const settle = async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  };

  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({
      imports: [StockDetailComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        provideAnimationsAsync(),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: convertToParamMap({ id: '1' }) },
            paramMap: of(convertToParamMap({ id: '1' }))
          }
        }
      ]
    }).compileComponents();
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(StockDetailComponent);
    // o componente importa MatSnackBarModule: espiona a instância dele
    snack = { open: vi.fn() };
    (fixture.componentInstance as unknown as { snackBar: MatSnackBar }).snackBar = snack as unknown as MatSnackBar;
    await settle();
  });

  it('keeps the item on screen and only warns when a reload fails', async () => {
    backend.expectOne('/api/v1/stock/items/1').flush(item);
    backend.match('/api/v1/stock/movements/item/1').forEach((r) => r.flush([]));
    await settle();
    expect(fixture.nativeElement.textContent).toContain('Cabo HDMI');

    fixture.componentInstance.loadItem('1'); // recarga (como após registrar uma movimentação)
    backend.expectOne('/api/v1/stock/items/1').flush({ error: { message: 'Falha temporária.' } }, { status: 503, statusText: 'x' });
    await settle();

    expect(fixture.nativeElement.textContent).toContain('Cabo HDMI'); // a tela continua
    expect(fixture.nativeElement.querySelector('[data-testid="state-error"]')).toBeNull();
    expect(snack.open).toHaveBeenCalledTimes(1);
  });

  it('on the very first load, a failure still shows the error screen with retry', async () => {
    backend.expectOne('/api/v1/stock/items/1').flush({}, { status: 500, statusText: 'x' });
    await settle();
    expect(fixture.nativeElement.querySelector('[data-testid="state-error"]')).toBeTruthy();
    expect(snack.open).not.toHaveBeenCalled();
  });
});
