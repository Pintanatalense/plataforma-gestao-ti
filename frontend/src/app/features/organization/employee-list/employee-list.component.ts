import { Component, OnInit, inject, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { apiErrorMessage } from '../../../core/http/api-error';
import { LoadStateComponent } from '../../../shared/components/load-state/load-state.component';
import { OrganizationService, Employee } from '../../../core/services/organization.service';
import { EmployeeDialogComponent } from './employee-dialog.component';

@Component({
  selector: 'app-employee-list',
  standalone: true,
  imports: [
    CommonModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatDialogModule,
    MatSnackBarModule,
    LoadStateComponent
  ],
  templateUrl: './employee-list.component.html',
  styleUrls: ['./employee-list.component.scss']
})
export class EmployeeList implements OnInit {
  private orgService = inject(OrganizationService);
  private dialog = inject(MatDialog);
  private snackBar = inject(MatSnackBar);
  private cdr = inject(ChangeDetectorRef);

  displayedColumns: string[] = ['sector', 'registration', 'name', 'phone', 'job_title', 'status', 'actions'];
  dataSource: Employee[] = [];

  /** Primeira carga em andamento / falha (uma recarga que falha mantém a tabela e só avisa). */
  isLoading = true;
  loadError: string | null = null;
  private loaded = false;

  ngOnInit(): void {
    this.loadData();
  }

  loadData() {
    if (!this.loaded) {
      this.isLoading = true;
      this.loadError = null;
    }
    this.orgService.getEmployees().subscribe({
      next: (data) => {
        this.dataSource = data;
        this.loaded = true;
        this.isLoading = false;
        this.loadError = null;
        this.cdr.markForCheck();
      },
      error: (err) => {
        const msg = apiErrorMessage(err, 'Erro ao carregar colaboradores.');
        if (this.loaded) {
          this.snackBar.open(msg, 'Fechar', { duration: 4000 });
        } else {
          this.isLoading = false;
          this.loadError = msg;
        }
        this.cdr.markForCheck();
      }
    });
  }

  openDialog(employee?: Employee) {
    const dialogRef = this.dialog.open(EmployeeDialogComponent, {
      width: '400px',
      data: employee || null
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        if (employee) {
          this.orgService.updateEmployee(employee.id, result).subscribe({
            next: () => {
              this.snackBar.open('Colaborador atualizado com sucesso', 'Fechar', { duration: 3000 });
              this.loadData();
            },
            error: (err) => {
              this.snackBar.open(apiErrorMessage(err, 'Erro ao atualizar colaborador'), 'Fechar', { duration: 4000 });
            }
          });
        } else {
          this.orgService.createEmployee(result).subscribe({
            next: () => {
              this.snackBar.open('Colaborador criado com sucesso', 'Fechar', { duration: 3000 });
              this.loadData();
            },
            error: (err) => {
              this.snackBar.open(apiErrorMessage(err, 'Erro ao criar colaborador'), 'Fechar', { duration: 4000 });
            }
          });
        }
      }
    });
  }

  deleteEmployee(id: string) {
    if (confirm('Tem certeza que deseja inativar/remover este colaborador?')) {
      this.orgService.deleteEmployee(id).subscribe({
        next: () => {
          this.snackBar.open('Colaborador inativado com sucesso', 'Fechar', { duration: 3000 });
          this.loadData();
        },
        error: (err) => {
          this.snackBar.open(apiErrorMessage(err, 'Erro ao inativar colaborador'), 'Fechar', { duration: 4000 });
        }
      });
    }
  }
}
