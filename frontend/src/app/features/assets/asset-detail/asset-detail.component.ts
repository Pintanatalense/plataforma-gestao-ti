import { Component, OnInit, ViewChild, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { MatTabsModule } from '@angular/material/tabs';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { HttpEventType, HttpResponse } from '@angular/common/http';

import { Asset, AssetMovement, AssetService } from '../../../core/services/asset.service';
import { Employee, OrganizationService, Unit } from '../../../core/services/organization.service';
import { AttachmentsService, Attachment } from '../../../core/services/attachments.service';
import { AttachmentsComponent } from '../../../shared/components/attachments/attachments.component';

@Component({
  selector: 'app-asset-detail',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatTabsModule,
    MatButtonModule,
    MatIconModule,
    MatSnackBarModule,
    MatTooltipModule,
    MatProgressBarModule,
    AttachmentsComponent
  ],
  templateUrl: './asset-detail.component.html',
  styleUrls: ['./asset-detail.component.scss']
})
export class AssetDetailComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private assetService = inject(AssetService);
  private orgService = inject(OrganizationService);
  private attachmentsService = inject(AttachmentsService);
  private snackBar = inject(MatSnackBar);

  @ViewChild('attachmentsComp') attachmentsComp?: AttachmentsComponent;

  asset: Asset | null = null;
  movements: AssetMovement[] = [];
  specEntries: [string, any][] = [];

  units: Unit[] = [];
  employees: Employee[] = [];
  attachments: Attachment[] = [];

  isUploadingStatement = false;
  uploadProgress = 0;

  ngOnInit(): void {
    const assetId = this.route.snapshot.paramMap.get('id');
    if (assetId) {
      this.loadAsset(assetId);
      this.loadMovements(assetId);
      this.loadAttachments(assetId);
    }
    this.loadDependencies();
  }

  loadAsset(id: string): void {
    this.assetService.getAsset(id).subscribe({
      next: (asset) => {
        this.asset = asset;
        this.specEntries = asset.technical_specs ? Object.entries(asset.technical_specs) : [];
      },
      error: (err) => console.error('Erro ao carregar ativo:', err)
    });
  }

  loadMovements(id: string): void {
    this.assetService.getMovementsByAsset(id).subscribe({
      next: (movs) => (this.movements = movs),
      error: (err) => console.error('Erro ao carregar movimentações:', err)
    });
  }

  loadAttachments(id?: string): void {
    const assetId = id || this.asset?.id;
    if (!assetId) return;
    this.attachmentsService.getAttachments('ASSET', assetId).subscribe({
      next: (atts) => (this.attachments = atts),
      error: (err) => console.error('Erro ao carregar anexos do ativo:', err)
    });
  }

  onAttachmentsChanged(atts: Attachment[]): void {
    this.attachments = atts;
  }

  get hasSignedStatement(): boolean {
    return !!this.signedStatementFile;
  }

  get signedStatementFile(): Attachment | undefined {
    if (!this.attachments || this.attachments.length === 0) return undefined;
    const byKeyword = this.attachments.find((att) => {
      const name = att.filename.toLowerCase();
      return (
        name.includes('termo') ||
        name.includes('cautela') ||
        name.includes('assinado') ||
        name.includes('responsabilidade')
      );
    });
    if (byKeyword) return byKeyword;
    return this.attachments.find((att) => att.filename.toLowerCase().endsWith('.pdf'));
  }

  onUploadStatementFile(event: any): void {
    const file: File = event.target.files?.[0];
    if (!file || !this.asset) return;

    this.isUploadingStatement = true;
    this.uploadProgress = 0;

    this.attachmentsService.uploadFile(file, 'ASSET', this.asset.id).subscribe({
      next: (httpEvent: any) => {
        if (httpEvent.type === HttpEventType.UploadProgress) {
          this.uploadProgress = Math.round((100 * httpEvent.loaded) / (httpEvent.total || file.size));
        } else if (httpEvent instanceof HttpResponse) {
          this.isUploadingStatement = false;
          this.snackBar.open('Termo assinado anexado com sucesso ao ativo!', 'OK', { duration: 3500 });
          this.loadAttachments();
          if (this.attachmentsComp) {
            this.attachmentsComp.loadAttachments();
          }
        }
      },
      error: (err) => {
        this.isUploadingStatement = false;
        this.snackBar.open(err.error?.detail || 'Erro ao anexar termo assinado', 'Fechar', { duration: 4000 });
      }
    });

    event.target.value = null;
  }

  downloadAttachment(attachment: Attachment): void {
    this.attachmentsService.downloadAttachment(attachment.id, attachment.filename);
  }

  loadDependencies(): void {
    this.orgService.getUnits().subscribe({
      next: (units) => (this.units = units),
      error: (err) => console.error('Erro ao carregar unidades:', err)
    });

    this.orgService.getEmployees().subscribe({
      next: (emps) => (this.employees = emps),
      error: (err) => console.error('Erro ao carregar colaboradores:', err)
    });
  }

  getUnitName(unitId?: string): string {
    if (!unitId) return 'N/A';
    const found = this.units.find((u) => u.id === unitId);
    return found ? found.name : 'N/A';
  }

  getEmployeeName(employeeId?: string | null): string {
    if (!employeeId) return 'Nenhum (Em Estoque)';
    const found = this.employees.find((e) => e.id === employeeId);
    return found ? `${found.name} (${found.registration})` : 'Colaborador';
  }

  printResponsibilityStatement(): void {
    if (!this.asset) return;
    this.assetService.openResponsibilityStatement(this.asset.id);
  }
}
