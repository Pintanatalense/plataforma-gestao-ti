import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter, Router } from '@angular/router';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { MatSnackBar } from '@angular/material/snack-bar';
import { of } from 'rxjs';
import { TicketCreateComponent } from './ticket-create.component';

describe('Abrir chamado: anexo que falha não pode virar "sucesso"', () => {
  let fixture: ComponentFixture<TicketCreateComponent>;
  let component: TicketCreateComponent;
  let backend: HttpTestingController;
  let snack: { open: ReturnType<typeof vi.fn> };

  const submit = async (attachmentStatus: number | null) => {
    component.ticketForm.patchValue({ title: 'Mouse', description: 'Não funciona' });
    component.selectedFiles = [new File(['x'], 'foto.png', { type: 'image/png' })];
    component.onSubmit();
    backend.expectOne((r) => r.method === 'POST' && r.url === '/api/v1/tickets').flush({ id: 't1' });
    await fixture.whenStable();
    const upload = backend.expectOne((r) => r.method === 'POST' && r.url === '/api/v1/attachments');
    if (attachmentStatus === null) upload.flush({ id: 'a1' });
    else upload.flush({ error: { message: 'x' } }, { status: attachmentStatus, statusText: 'x' });
    await fixture.whenStable();
    await new Promise((r) => setTimeout(r, 0));
  };

  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({
      imports: [TicketCreateComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        provideNoopAnimations(),
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({}), queryParamMap: convertToParamMap({}) } } }
      ]
    }).compileComponents();
    backend = TestBed.inject(HttpTestingController);
    vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    fixture = TestBed.createComponent(TicketCreateComponent);
    component = fixture.componentInstance;
    snack = { open: vi.fn() };
    (component as unknown as { snackBar: MatSnackBar }).snackBar = snack as unknown as MatSnackBar;
    fixture.detectChanges();
    backend.match(() => true); // chamadas do ngOnInit (categorias, ativos): não interessam aqui
    void of;
  });

  it('warns which attachments were NOT sent instead of announcing full success', async () => {
    await submit(500);
    const msg = snack.open.mock.calls[0][0] as string;
    expect(msg).toContain('NÃO foram enviados');
    expect(msg).toContain('foto.png');
    expect(msg).not.toContain('com sucesso com');
  });

  it('announces success when every attachment went through', async () => {
    await submit(null);
    expect(snack.open.mock.calls[0][0]).toContain('com sucesso com 1 anexo');
  });
});
