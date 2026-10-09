import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { TicketService, TicketCategory } from '../ticket.service';
import { OrganizationService, Sector } from '../../../core/services/organization.service';

@Component({
  selector: 'app-category-list',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatButtonModule,
    MatInputModule,
    MatSelectModule,
    MatTableModule,
    MatIconModule,
    MatTooltipModule
  ],
  template: `
    <div class="page-container">
      <div class="page-header">
        <div class="title-area">
          <h1>Categorias de Chamados</h1>
          <p>Gerencie as categorias de suporte e configure o roteamento automático para as filas.</p>
        </div>
      </div>

      <div class="content-grid">
        <div class="form-card">
          <div class="card-header">
            <h3>{{ editingCategory ? 'Editar Categoria' : 'Nova Categoria' }}</h3>
          </div>
          <form [formGroup]="catForm" (ngSubmit)="onSubmit()" class="modern-form">
            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Nome da Categoria</mat-label>
              <input matInput formControlName="name" placeholder="Ex: Manutenção de Hardware">
            </mat-form-field>
            
            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Descrição (Opcional)</mat-label>
              <textarea matInput formControlName="description" rows="3" placeholder="Detalhes sobre a categoria..."></textarea>
            </mat-form-field>

            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Setor Responsável (Fila Destino)</mat-label>
              <mat-select formControlName="default_sector_id">
                <mat-option [value]="null">Nenhum (Triagem)</mat-option>
                <mat-option *ngFor="let s of sectors" [value]="s.id">{{ s.name }}</mat-option>
              </mat-select>
              <mat-hint>Chamados desta categoria serão enviados para este setor automaticamente.</mat-hint>
            </mat-form-field>

            <div class="form-actions">
              <button mat-button type="button" *ngIf="editingCategory" (click)="cancelEdit()" class="cancel-btn">Cancelar</button>
              <button mat-flat-button color="primary" type="submit" [disabled]="catForm.invalid" class="submit-btn">
                <mat-icon>{{ editingCategory ? 'save' : 'add' }}</mat-icon>
                {{ editingCategory ? 'Atualizar' : 'Criar' }}
              </button>
            </div>
          </form>
        </div>

        <div class="table-card">
          <table mat-table [dataSource]="categories" class="modern-table">
            <ng-container matColumnDef="name">
              <th mat-header-cell *matHeaderCellDef> Categoria </th>
              <td mat-cell *matCellDef="let element">
                <div class="category-info">
                  <span class="category-name">{{element.name}}</span>
                  <span class="category-desc" *ngIf="element.description">{{element.description}}</span>
                </div>
              </td>
            </ng-container>

            <ng-container matColumnDef="sector">
              <th mat-header-cell *matHeaderCellDef> Roteamento (Setor) </th>
              <td mat-cell *matCellDef="let element"> 
                <span class="status-badge" [class.routed]="element.default_sector_id" [class.triage]="!element.default_sector_id">
                  <mat-icon class="badge-icon">{{ element.default_sector_id ? 'route' : 'filter_alt' }}</mat-icon>
                  {{ element.default_sector_id ? getSectorName(element.default_sector_id) : 'Triagem' }}
                </span>
              </td>
            </ng-container>

            <ng-container matColumnDef="actions">
              <th mat-header-cell *matHeaderCellDef class="actions-header"> Ações </th>
              <td mat-cell *matCellDef="let element" class="actions-cell">
                <button mat-icon-button class="action-btn edit-btn" (click)="edit(element)" matTooltip="Editar">
                  <mat-icon>edit</mat-icon>
                </button>
              </td>
            </ng-container>

            <tr mat-header-row *matHeaderRowDef="displayedColumns"></tr>
            <tr mat-row *matRowDef="let row; columns: displayedColumns;"></tr>
            
            <tr class="mat-row" *matNoDataRow>
              <td class="mat-cell empty-state" [attr.colspan]="displayedColumns.length">
                <mat-icon>category</mat-icon>
                <p>Nenhuma categoria encontrada</p>
              </td>
            </tr>
          </table>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .page-container {
      display: flex;
      flex-direction: column;
      gap: 32px;
      padding: 32px;
      background: var(--mat-sys-surface-container-lowest);
      min-height: calc(100vh - 64px);
      animation: fadeIn 0.4s ease-out;
    }

    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(10px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .page-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: var(--mat-sys-surface);
      padding: 32px;
      border-radius: 28px;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.04);
      border: 1px solid var(--mat-sys-outline-variant);

      .title-area {
        h1 {
          margin: 0;
          padding: 10px 0;
          line-height: normal;
          font-size: 32px;
          font-weight: 800;
          letter-spacing: -0.5px;
          color: var(--mat-sys-primary);
        }
        p {
          margin: 8px 0 0;
          color: var(--mat-sys-on-surface-variant);
          font-size: 15px;
        }
      }
    }

    .content-grid {
      display: grid;
      grid-template-columns: 400px 1fr;
      gap: 32px;
      align-items: start;
    }

    .form-card, .table-card {
      background: var(--mat-sys-surface);
      border-radius: 28px;
      overflow: hidden;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.04);
      border: 1px solid var(--mat-sys-outline-variant);
    }

    .form-card {
      padding: 32px;
      
      .card-header {
        margin-bottom: 24px;
        h3 {
          margin: 0;
          color: var(--mat-sys-primary);
          font-size: 20px;
          font-weight: 700;
        }
      }
    }

    .modern-form {
      display: flex;
      flex-direction: column;
      gap: 8px;
      
      .full-width { width: 100%; }
      
      .form-actions {
        display: flex;
        justify-content: flex-end;
        gap: 12px;
        margin-top: 16px;
        
        .cancel-btn {
          border-radius: 12px;
          font-weight: 600;
        }
        
        .submit-btn {
          border-radius: 12px;
          padding: 0 24px;
          height: 44px;
          font-weight: 600;
          transition: transform 0.2s, box-shadow 0.2s;
          
          &:not([disabled]):hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(var(--mat-sys-primary-rgb), 0.3);
          }
          
          mat-icon { margin-right: 8px; }
        }
      }
    }

    .modern-table {
      width: 100%;
      
      tr.mat-mdc-row {
        transition: background-color 0.2s ease;
        &:hover {
          background-color: var(--mat-sys-surface-container-highest);
        }
      }

      td.mat-mdc-cell, th.mat-mdc-header-cell {
        border-bottom-color: var(--mat-sys-outline-variant);
        padding: 20px 24px;
      }
      
      th.mat-mdc-header-cell {
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        font-size: 12px;
        color: var(--mat-sys-on-surface-variant);
        background: var(--mat-sys-surface-container-lowest);
      }
    }

    .category-info {
      display: flex;
      flex-direction: column;
      gap: 4px;
      
      .category-name {
        font-weight: 700;
        font-size: 15px;
        color: var(--mat-sys-on-surface);
      }
      
      .category-desc {
        font-size: 13px;
        color: var(--mat-sys-on-surface-variant);
        line-height: 1.4;
      }
    }

    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 14px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.5px;
      text-transform: uppercase;
      
      .badge-icon {
        font-size: 16px;
        height: 16px;
        width: 16px;
      }

      &.routed {
        background-color: rgba(var(--mat-sys-primary-rgb), 0.12);
        color: var(--mat-sys-primary);
      }
      
      &.triage {
        background-color: var(--mat-sys-surface-container-highest);
        color: var(--mat-sys-on-surface-variant);
      }
    }

    .actions-header {
      text-align: right !important;
      width: 80px;
    }

    .actions-cell {
      text-align: right;
      
      .action-btn {
        transition: transform 0.2s, background-color 0.2s, color 0.2s;
        &.edit-btn {
          color: var(--mat-sys-primary);
          &:hover {
            background-color: rgba(var(--mat-sys-primary-rgb), 0.1);
            transform: scale(1.1);
          }
        }
      }
    }

    .empty-state {
      text-align: center;
      padding: 64px 32px !important;
      color: var(--mat-sys-on-surface-variant);
      
      mat-icon {
        font-size: 48px;
        height: 48px;
        width: 48px;
        opacity: 0.5;
        margin-bottom: 16px;
      }
      
      p {
        margin: 0;
        font-size: 16px;
        font-weight: 500;
      }
    }
  `]
})
export class CategoryListComponent implements OnInit {
  private ticketService = inject(TicketService);
  private orgService = inject(OrganizationService);
  private fb = inject(FormBuilder);

  categories: TicketCategory[] = [];
  sectors: Sector[] = [];
  displayedColumns: string[] = ['name', 'sector', 'actions'];
  
  catForm: FormGroup;
  editingCategory: TicketCategory | null = null;

  constructor() {
    this.catForm = this.fb.group({
      name: ['', Validators.required],
      description: [''],
      default_sector_id: [null]
    });
  }

  ngOnInit() {
    this.loadData();
    this.orgService.getSectors().subscribe(s => this.sectors = s);
  }

  loadData() {
    this.ticketService.getCategories().subscribe(c => this.categories = c);
  }

  getSectorName(id: string): string {
    const s = this.sectors.find(x => x.id === id);
    return s ? s.name : 'Desconhecido';
  }

  edit(cat: TicketCategory) {
    this.editingCategory = cat;
    this.catForm.patchValue({
      name: cat.name,
      description: cat.description,
      default_sector_id: cat.default_sector_id
    });
  }

  cancelEdit() {
    this.editingCategory = null;
    this.catForm.reset();
  }

  onSubmit() {
    if (this.catForm.valid) {
      if (this.editingCategory) {
        this.ticketService.updateCategory(this.editingCategory.id, this.catForm.value).subscribe(() => {
          this.loadData();
          this.cancelEdit();
        });
      } else {
        this.ticketService.createCategory(this.catForm.value).subscribe(() => {
          this.loadData();
          this.catForm.reset();
        });
      }
    }
  }
}
