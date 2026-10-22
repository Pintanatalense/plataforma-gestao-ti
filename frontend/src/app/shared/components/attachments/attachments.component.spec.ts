import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { AttachmentsComponent } from './attachments.component';

describe('AttachmentsComponent: falha ao listar', () => {
  let fixture: ComponentFixture<AttachmentsComponent>;
  let backend: HttpTestingController;
  const URL = (r: { url: string }) => r.url.startsWith('/api/v1/attachments');
  const settle = async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AttachmentsComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideAnimationsAsync()]
    }).compileComponents();
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(AttachmentsComponent);
    fixture.componentRef.setInput('entityType', 'TICKET');
    fixture.componentRef.setInput('entityId', 't1');
    await settle();
  });

  it('shows an error with retry (the list may exist and just not have been read)', async () => {
    backend.expectOne(URL).flush({ error: { message: 'Sem acesso.' } }, { status: 403, statusText: 'x' });
    await settle();
    const el = fixture.nativeElement.querySelector('[data-testid="attachments-error"]') as HTMLElement;
    expect(el.textContent).toContain('Sem acesso.');
  });

  it('"Tentar novamente" asks for the list again and clears the error on success', async () => {
    backend.expectOne(URL).flush({}, { status: 500, statusText: 'x' });
    await settle();
    (fixture.nativeElement.querySelector('[data-testid="attachments-retry"]') as HTMLButtonElement).click();
    backend.expectOne(URL).flush([]);
    await settle();
    expect(fixture.nativeElement.querySelector('[data-testid="attachments-error"]')).toBeNull();
  });
});
