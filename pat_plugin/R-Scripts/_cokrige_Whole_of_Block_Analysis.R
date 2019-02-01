
##################################################################################
## test file date: 21/01/2019
## coKrigingSoft version 1.0
##################################################################################

##################################################################################
## two parameter setting
nBins    <- 20;      # keep same with the one within vesper
propMaxD <- 0.333333 # 1/3 is recommended by gstat, and verified by several data sets we have tested
##################################################################################

##################################################################################
## Required packages ##
##################################################################################

# check the R version
#if(as.integer(R.Version()$major)<3 | (as.integer(R.Version()$major)==3 & as.numeric(R.Version()$minor)<5.1)) stop("The R base version needs to upgrade to 3.5.1.");

lib <- c("sp","gstat","fields","mgcv","spTimer","rgdal","raster","gdalUtils","stringr")
lib.loc <- paste0(Sys.getenv("USERPROFILE"),"/.qgis2/processing/rlibs/")
install.libraries <- function(lib=NULL){
  new <- lib[!(lib %in% installed.packages(lib.loc = lib.loc)[, "Package"])]
  if (length(new)){   
    install.packages(new, lib = lib.loc, dependencies = TRUE)
  }
}
load.libraries <- function(lib=NULL){
  sapply(lib, require, lib.loc = lib.loc, character.only = TRUE)
}
install.libraries(lib)
load.libraries(c("sp","gstat","fields","mgcv","spTimer","rgdal","raster","gdalUtils","stringr"))


##################################################################################
## Required functions for QGIS
##################################################################################

run_fnc <- function(){
  # select treatment and data
  x.coords <- Easting; if(nchar(x.coords)>10){stop("Error in Easting column name. Cannot allow more than 10 characters.")}
  y.coords <- Northing; if(nchar(y.coords)>10){stop("Error in Northing column name. Cannot allow more than 10 characters.")}
  treatment.name <- Treatment_Column; if(nchar(treatment.name)>10){stop("Error in Treatment_Column column name. Cannot allow more than 10 characters.")}
  data.name <- Data_Column; if(nchar(data.name)>10){stop("Error in Data_Column column name. Cannot allow more than 10 characters.")}
  # check
  data <- as.data.frame(Input_Points_Layer@data)
  data <- data[,c(x.coords,y.coords,data.name,treatment.name)]
  data <- data[complete.cases(data), ]
  data <- data[order(data[,4]),]
  # model 
  md <- c("Global","Local")
  md <- md[Model+1]
  covModel <- c("Exp","Sph","Gau")
  covModel <- covModel[Covariance_Model+1]
  # dump the R console output 
  sink(paste0(path,Data_Column,"_dump_file_",md,covModel,"_.log"))
  out <- coKrig_R2QGIS(data=data)
  sink()
  # save into tif files 
  nms <- names(out)
  sink(paste0(path,Data_Column,"_list_of_tif_files_",md,covModel,"_.txt"))
  for(i in 1:ncol(out)){
    r <- out[,i]
    gridded(r) <- TRUE
    r <- raster(r)
    rc <- getRasterCentreWGS84XY(inRaster=Input_Block_Grid) 
    nationalCRS <- getProjectedCRSForXY(rc$x_coord, rc$y_coord, rc$xy_epsg)
    r <- mask(r, Input_Block_Grid)
    #crs(r) <- crs(Input_Block_Grid)
    crs(r) <- nationalCRS
	ddir <- dir(path)
	if(class(try(writeRaster(r,paste0(path,data.name,"_",nms[i],"_",md,covModel,"_.tif"),options=c("TFW=YES"), overwrite=TRUE, NAflag = -9999)))=="try-error"){
	 stop(paste0("Error in writeRaster(). File is in use. Cannot write to ",data.name,"_",nms[i],"_",md,covModel,"_.tif")) 
	}
	print(paste0(path,data.name,"_",nms[i],"_",md,covModel,"_.tif"),options=c("TFW=YES"))
  }
  sink()
  print("Whole of Block Analysis has been Completed Successfully")
  print(paste0(path,Data_Column,"_list_of_tif_files_",md,covModel,"_.txt"))
}
##
coKrig_R2QGIS <- function(data=data){
  # check the neighbourhood size 
  if(User_Defined_Neighbourhood_for_Local_CoKriging==TRUE){
    neighbourhood.size <- Input_Neighbourhood_Size_in_Metre
  }
  else{
    neighbourhood.size <- NULL
  }
  #
  tr <- sort(unique(data[,4]))
  pr.res <- list()
  pr.res$data.column <- Data_Column
  if(length(tr)==3){  
   pr.res$treatment.labels <- paste0("tr1 = ",tr[1],", tr2 = ",tr[2],", tr3 = ",tr[3])
  }
  else if(length(tr)==2){  
   pr.res$treatment.labels <- paste0("tr1= ",tr[1],", tr2 = ",tr[2])
  }
  else if(length(tr)==1){  
   pr.res$treatment.labels <- paste0("tr1 = ",tr[1])
  }
  else{  
    stop("Maximum 3 treatments are allowed.")
  }
  #
  mod <- c("global","local-processed")
  mod <- mod[Model+1]
  covModel <- c("Exp","Sph","Gau")
  covModel <- covModel[Covariance_Model+1]
  #
  # dump the R console output 
  result <- .coKrig_inner_fnc(data = data, 
                              type = mod,
                              local.tuning = NULL,
                              grid.coords = coordinates(Input_Block_Grid),
                              model = covModel,
                              neighbourhood.size = neighbourhood.size,
                              plot.global = FALSE,
                              tol.site = 1500) 
  #
  ck <- as.matrix(result$kriged.output)
  #
  result$kriged.output <- NULL
  result$grid.size <- NULL
  result$shapefile <- NULL
  #  
  pr.res$computing.time <- result$comp.time
  pr.res$covariance.model <- result$model
  pr.res$coKriging.type <- result$type
  pr.res$estimated.parameters <- result$est.parameters
  pr.res$sample.size <- result$est.sample
  if(result$type=="local-processed"){
    pr.res$neighbourhood.size <- result$neighbourhood.size
    pr.res$coKriging.type <- "local"
  }
  pr.res$grid.counts <- nrow(result$grid.coordinates)
  pr.res$grid.coordinates <- result$grid.coordinates
  class(pr.res) <- class(result)
  rm(result)
  #
  md <- c("Global","Local")
  md <- md[Model+1]
  sink(paste0(path,Data_Column,"_model_parameters_",md,covModel,"_.txt"))
  print(pr.res)  
  sink()
  #	
  #if(length(nms)==9){
  if(ncol(ck)==9){
    mat <- matrix(NA,nrow(ck),6+6+3+3)
    mat[,1:6] <- ck[,1:6]
    mat[,7] <- ck[,1]-ck[,3]; mat[,8] <- abs(ck[,2] + ck[,4] - 2*ck[,7]) #12
    mat[,9] <- ck[,1]-ck[,5]; mat[,10] <- abs(ck[,2] + ck[,6] - 2*ck[,8]) #13
    mat[,11] <- ck[,3]-ck[,5]; mat[,12] <- abs(ck[,4] + ck[,6] - 2*ck[,9]) #23
    mat[,13] <- mat[,7]/sqrt(mat[,8]) # z test stat for 12 
    mat[,14] <- mat[,9]/sqrt(mat[,10]) # z test stat for 13 
    mat[,15] <- mat[,11]/sqrt(mat[,12]) # z test stat for 23 
    mat[,16] <-  sapply(mat[,13],p.val.2tailed) # p for 12 
    mat[,17] <-  sapply(mat[,14],p.val.2tailed) # p for 13 
    mat[,18] <-  sapply(mat[,15],p.val.2tailed) # p for 23 
    colnames(mat) <- c(paste0("tr_",tr[1]),paste0("tr_",tr[1],"_var"),paste0("tr_",tr[2]),paste0("tr_",tr[2],"_var"),paste0("tr_",tr[3]),paste0("tr_",tr[3],"_var"),
    paste0("tr_diff_",tr[1],"_",tr[2]),paste0("tr_diff_",tr[1],"_",tr[2],"_cov"),paste0("tr_diff_",tr[1],"_",tr[3]),paste0("tr_diff_",tr[1],"_",tr[3],"_cov"),	
	paste0("tr_diff_",tr[2],"_",tr[3]),paste0("tr_diff_",tr[2],"_",tr[3],"_cov"),paste0("z_",tr[1],"_",tr[2]),paste0("z_",tr[1],"_",tr[3]),paste0("z_",tr[2],"_",tr[3]),
	paste0("p_val_",tr[1],"_",tr[2]),paste0("p_val_",tr[1],"_",tr[3]),paste0("p_val_",tr[2],"_",tr[3]))
  }
  else if(ncol(ck)==5){
    mat <- matrix(NA,nrow(ck),4+2+1+1)
    mat[,1:4] <- ck[,1:4]
    mat[,5] <- ck[,1]-ck[,3]; mat[,6] <- abs(ck[,2] + ck[,4] - 2*ck[,7]) #12
    mat[,7] <- mat[,5]/sqrt(mat[,6]) # z test stat for 12 
    mat[,8] <- sapply(mat[,7],p.val.2tailed) # p for 12
    colnames(mat) <- c(paste0("tr_",tr[1]),paste0("tr_",tr[1],"_var"),paste0("tr_",tr[2]),paste0("tr_",tr[2],"_var"),
    paste0("tr_diff_",tr[1],"_",tr[2]),paste0("tr_diff_",tr[1],"_",tr[2],"_cov"),paste0("z_",tr[1],"_",tr[2]),paste0("p_val_",tr[1],"_",tr[2]))
  }
  else if(ncol(ck)==2){
    mat <- ck
    colnames(mat) <- c(paste0("tr_",tr[1]),paste0("tr_",tr[1],"_var")) 
  }
  else{
    stop("Error")
  }
  rm(ck)
  mat <- as.data.frame(cbind(coordinates(Input_Block_Grid),mat))
  coordinates(mat) <- names(mat)[1:2]
  #crs(mat) <- crs(Input_Block_Grid)
  mat
}
##
##################################################################################
## Required functions ##
##################################################################################
##
## calculate the p value  
	p.val.2tailed <- function(x){
	  x <- abs(x)
	  if(is.na(x)){
	   p <- NA
	  }
	  else if(x > 3.291){
	   p <- 0.001
	  }
	  else if(x > 2.576){
	   p <- 0.01
	  }
	  else if(x > 1.960){
	   p <- 0.05
	  }
	  else if(x > 1.645){
	   p <- 0.1
	  }
	  else if(x > 1.281){
	   p <- 0.2
	  }
	  else{
	   p <- 1
	  }
	  p
	}
##
set.seed(1234)
# parallel function
coKrig <- 
  function(data = NULL,
           type = "global",
           local.tuning = NULL,
           grid.size = NULL,
           grid.coords = NULL,
           shapefile = NULL,
           model = "Exp",
           neighbourhood.size = NULL,
           plot.global = FALSE,
           plot.local = FALSE,
           tol.site = 1000,
           sub.replicate = 10,
           sub.percentage = 10,
           parallel = FALSE,
           numCores = NULL,
           ...) {
    #
    #
    # type = "global", "local-adaptive", "local-processed", "kmeans", "boot", "epoch"
    #        "local-processed" => using gam
    #        "epoch" => based on NN stochastic gradient descent, sampling without replacement 
    #
    # local.tuning = only applicable for local-processed to define the number of kmeans sample
    #                varies between 0 to inf; 
    #                default is 2  
    #
    # grid.size = user defined grid.size for kriging, format c(10,10), ie, 10x10 grid 
    # grid.coords = user defined coordinate points
    # shapefile = user defined shapefile for kriging
    # model =  "Exp", "Sph", "Gau"
    # plot.global = if TRUE, plot variograms
    # grid.size = user defined grid.size for kriging, format c(10,10), ie, 10x10 grid 
    # grid.coords = user defined coordinate points
    # shapefile = user defined shapefile for kriging
    #
    # model =  "Exp", "Sph", "Gau"
    #
    # neighbourhood.size => to be defined by user (default is a function of: (1) max-distance (2) range (3) no. of spatial points)
    # i.e., neighbourhood.size = f(phi,maxd,n); phi = range, maxd = max-distance, n = no. of spatial points.
    # f(phi,maxd,n) = phi * (n/maxd)^(-1), if (n/maxd)^(-1) > 1
    #               = phi, otherwise
    #
    # For big-n problem: neighbourhood.size = f(maxd,tol.site,n), i.e., neighbourhood.size  <- max(c(d))*(tol.site/nrow(d))
    #
    # plot.local = TRUE will return the local variograms for each kriging points.
    #
    # tol.site = maximum number of observation locations to fit a global model
    #
    # sub.replicate = number of replications used only for subsampling options
    # sub.percentage = percentage of samples/clusters used only for subsampling options
    #
    # parallel = logical, if TRUE then do parallel computing
    # numCore = only applicable for parallel computing, if NULL then code will find the number of cores of the computer and do the run
    #
    if(is.null(data)){
      stop("\n Define data frame \n")
    }
    if(!(is.data.frame(data) | is.matrix(data))){
      stop("\n Define data frame or data matrix correctly with 4 columns: col(1,2)=(x,y) coordinates, col(3)=yield/observations, col(4)=treatment types/numbers \n")
    }
    if(ncol(data) !=4){
      stop("\n Define data frame correctly with 4 columns: col(1,2)=(x,y) coordinates, col(3)=yield/observations, col(4)=treatment types/numbers \n")
    }
    if (!type %in% c("global", "local-adaptive", "local-processed", "kmeans", "boot", "epoch")) {
      stop("\n Define model correctly: global, local-adaptive, local-processed, kmeans, boot, epoch \n")
    }
    #
    if(parallel==TRUE){
      # check the prediction grid/coordinates 
      if (is.null(grid.size) &
          is.null(grid.coords) & is.null(shapefile)) {
        stop("\n Provide a value for the argument grid.size, grid.coords or shapefile \n")
      }
      else if (!is.null(grid.size)) {
        gr <- spT.grid.coords(x, y, by = grid.size)
      }
      else if (!is.null(grid.coords)) {
        gr <- as.matrix(grid.coords)
      }
      else if (!is.null(shapefile)) {
        gr <- as.matrix(coordinates(shapefile))
      }
      else {
        stop("\n Provide a value for the argument grid.size, grid.coords or shapefile \n")
      }
      # start the parallel process
      if(is.null(numCores)){
        # Calculate the number of cores
        numCores <- detectCores() - 1
        # Initiate cluster
        cl <- makeCluster(numCores)
      }
      else{
        # Initiate cluster
        cl <- makeCluster(numCores)
      }
      breaks <- round(seq(1,nrow(gr),length.out=(numCores+1)))
      breaks[1] <- 0
      if(breaks[numCores+1] != nrow(gr)){breaks[numCores+1] <- nrow(gr)}
      para_fnc <- function(i){
        gr.ck <- gr[((1)+breaks[i]):breaks[i+1],]
        .coKrig_inner_fnc(data = data,
                          type = type,
                          local.tuning = local.tuning,
                          grid.size = NULL,
                          grid.coords = gr.ck,
                          shapefile = NULL,
                          model = model,
                          neighbourhood.size = neighbourhood.size,
                          plot.global = plot.global,
                          plot.local = plot.local,
                          tol.site = tol.site,
                          sub.replicate = sub.replicate,
                          sub.percentage = sub.percentage,
                          ...)
      }
      print(numCores)
      out <- mclapply(1:numCores,para_fnc,mc.cores=numCores)
      n <- unique(unlist(lapply(out, names)))
      names(n) <- n
      #out <- lapply(n, function(i) unlist(lapply(out, `[[`, i)))
      out <- lapply(n, function(i) (lapply(out, `[[`, i)))
      out$kriged.output <- do.call(rbind,out$kriged.output)
      out$grid.coordinates <- do.call(rbind,out$grid.coordinates)
      n <- names(out)[!(names(out)%in%c("kriged.output","grid.coordinates"))]
      out[n] <- lapply(out[n],unlist)
      stopCluster(cl)
      class(out) <- "cokriging"
      out
    }
    else if(parallel==FALSE){
      .coKrig_inner_fnc(data = data,
                        type = type,
                        local.tuning = local.tuning,
                        grid.size = grid.size,
                        grid.coords = grid.coords,
                        shapefile = shapefile,
                        model = model,
                        neighbourhood.size = neighbourhood.size,
                        plot.global = plot.global,
                        plot.local = plot.local,
                        tol.site = tol.site,
                        sub.replicate = sub.replicate,
                        sub.percentage = sub.percentage,
                        ...)
    }
    else{
      stop("Error: Define the argument 'parallel' correctly.")
    }
  }

#
# main function
.coKrig_inner_fnc <- 
  function(data = NULL,
           type = "global",
           local.tuning = NULL,
           grid.size = NULL,
           grid.coords = NULL,
           shapefile = NULL,
           model = "Exp",
           neighbourhood.size = NULL,
           plot.global = FALSE,
           plot.local = FALSE,
           tol.site = 1500,
           sub.replicate,
           sub.percentage,
           ...) {
    #
    # type = "global", "local-adaptive", "local-processed", "kmeans", "boot", "epoch"
    #
    # local.tuning = only applicable for local-processed to define the number of kmeans sample
    #                varies between 0 to inf; 
    #                default is 2  
    #
    # grid.size = user defined grid.size for kriging, format c(10,10), ie, 10x10 grid 
    # grid.coords = user defined coordinate points
    # shapefile = user defined shapefile for kriging
    # model =  "Exp", "Sph", "Gau"
    # plot.global = if TRUE, plot variograms
    # grid.size = user defined grid.size for kriging, format c(10,10), ie, 10x10 grid 
    # grid.coords = user defined coordinate points
    # shapefile = user defined shapefile for kriging
    #
    # model =  "Exp", "Sph", "Gau"
    #
    # neighbourhood.size => to be defined by user (default is a function of: (1) max-distance (2) range (3) no. of spatial points)
    # i.e., neighbourhood.size = f(phi,maxd,n); phi = range, maxd = max-distance, n = no. of spatial points.
    # f(phi,maxd,n) = phi * (n/maxd)^(-1), if (n/maxd)^(-1) > 1
    #               = phi, otherwise
    #
    # For big-n problem: neighbourhood.size = f(maxd,tol.site,n), i.e., neighbourhood.size  <- max(c(d))*(tol.site/nrow(d))
    #
    # plot.local = TRUE will return the local variograms for each kriging points.
    #
    # tol.site = maximum number of observation locations to fit a global model
    #
    # sub.replicate = number of replications used only for subsampling options
    # sub.percentage = percentage of samples/clusters used only for subsampling options
    #
    #
    start.time <- proc.time()[3]
    options(warn=-1)
    if(is.null(data)){
      stop("\n Define data frame \n")
    }
    if(!(is.data.frame(data) | is.matrix(data))){
      stop("\n Define data frame or data matrix correctly with 4 columns: col(1,2)=(x,y) coordinates, col(3)=yield/observations, col(4)=treatment types/numbers \n")
    }
    if(ncol(data) !=4){
      stop("\n Define data frame correctly with 4 columns: col(1,2)=(x,y) coordinates, col(3)=yield/observations, col(4)=treatment types/numbers \n")
    }
    if (!type %in% c("global", "local-adaptive", "local-processed", "kmeans", "boot", "epoch")) {
      stop("\n Define model correctly: global, local-adaptive, local-processed, kmeans, boot, epoch \n")
    }
    if(type=="global"){
      out <- ._Global_fnc(data=data,
                          grid.size=grid.size,
                          grid.coords=grid.coords,
                          shapefile=shapefile,
                          model=model,
                          plot.global=plot.global,
                          tol.site=tol.site,
                          ...)      
    }
    else if(type=="local-adaptive"){
      out <- ._Local_fnc(data=data,
                         model=model,
                         grid.size=grid.size,
                         grid.coords=grid.coords,
                         shapefile=shapefile,
                         block.size=neighbourhood.size,
                         plot.local=plot.local,
                         tol.site=tol.site,
                         ...)      
    }
    else if(type=="local-processed"){
      coords <- as.matrix(data[, 1:2])
      dimnames(coords) <- NULL
      x1 <- range(coords[, 1])
      x2 <- range(coords[, 2])
      if (is.null(grid.size) &
          is.null(grid.coords) & is.null(shapefile)) {
        stop("\n Provide a value for the argument grid.size, grid.coords or shapefile \n")
      }
      else if (!is.null(grid.size)) {
        gr <- spT.grid.coords(x1, x2, by = grid.size)
      }
      else if (!is.null(grid.coords)) {
        gr <- as.matrix(grid.coords)
      }
      else if (!is.null(shapefile)) {
        gr <- as.matrix(coordinates(shapefile))
      }
      else {
        stop("\n Provide a value for the argument grid.size, grid.coords or shapefile \n")
      }
      ck <- cbind(gr,1:nrow(gr))
      ch <- chull(gr[,1:2])
      gr.ck <- ck[ch,]
      ck <- ._Local_fnc(data=data,
                        model=model,
                        grid.size=NULL,
                        grid.coords=gr.ck[,1:2],
                        shapefile=NULL,
                        block.size=neighbourhood.size,
                        plot.local=FALSE,
                        tol.site=tol.site,
                        ...)$neighbourhood.size      
      #browser()
      names(ck) <- NULL
      gr.ck[,3] <- ck
      dimnames(gr.ck) <- NULL
      print(paste0("Estimating the 'Edge Effects' ... "))
      print(paste0("The initial maximum spatial range parameter is considered as: ", round(max(ck,na.rm=TRUE),4)))
      print(paste0("The initial minimum spatial range parameter is considered as: ", round(min(ck,na.rm=TRUE),4)))
      #
      ck <- cbind(gr,1:nrow(gr))
      ck <- ck[!(ck[,3]%in%ch),]
      ch <- c(ch, ch[1])
      ch <- gr[ch,]
      ch <- Polygon(ch,hole=FALSE)
      ch <- ch@area # area of the region 
      # 1/2*n*pi*r^2 = A
      if(is.null(local.tuning)){
        local.tuning <- 1 #2
      }
      else if(local.tuning<0){
        local.tuning <- 0
      }
      else{
        local.tuning <- local.tuning
      }
      #ch <- round((1/local.tuning)*(ch/(pi*min(gr.ck[,3])^2)))
      ch <- round((local.tuning*ch)/(pi*min(gr.ck[,3])^2))
      #print(ch)
      if(ch <= 50){ch <- 50}
      gr.ck2 <- kmeans(ck[,1:2],ch)$centers
      #ck <- ck[sample(nrow(ck),size=round(nrow(ck)*0.001)+1),] for random numbers 
      ck <- ._Local_fnc(data=data,
                        model=model,
                        grid.size=NULL,
                        grid.coords=gr.ck2[,1:2],
                        shapefile=NULL,
                        block.size=neighbourhood.size,
                        plot.local=FALSE,
                        tol.site=tol.site,
                        ...)$neighbourhood.size
      names(ck) <- NULL
      gr.ck2 <- cbind(gr.ck2,c(ck))
      dimnames(gr.ck2) <- NULL
      print(paste0("Number of kmean points: ", ch))
      print(paste0("The estimated average 'range' from kmean: ", round(mean(ck,na.rm=TRUE),4)))
      print(paste0("Estimating the 'Overall Effects' ... "))
      ## splines 
      gr.ck <- rbind(gr.ck,gr.ck2)
      gr.ck <- data.frame(gr.ck)
      names(gr.ck) <- c("x","y","z")
      fit <- gam(z~s(x,y),data=gr.ck); 
      gr <- data.frame(gr)
      names(gr) <- c("x","y")
      pr <- as.vector(predict(fit,gr))
      #pr[pr<=min(gr.ck[,3],na.rm=TRUE)] <- min(gr.ck[,3],na.rm=TRUE)
      rm(gr.ck)
      gr <- as.matrix(gr)
      ##
      out <-  ._Local_fnc_processed(data=data,
                                    model=model,
                                    grid.size=grid.size,
                                    grid.coords=grid.coords,
                                    shapefile=shapefile,
                                    #block.size=max(ck,na.rm=TRUE),
                                    block.size=pr,
                                    plot.local=plot.local,
                                    tol.site=tol.site,
                                    ...)       
    }
    else if(type=="kmeans"){
      pb <- txtProgressBar(min = 0, max = sub.replicate, style = 3)   # set progress bar
      if(sub.percentage <=0 | sub.percentage >100){stop("\n sub.percentage should be between 0 to 100")}
      out <- NULL
      n <- table(data[,4])
      nms <- names(table(data[,4]))
      if(length(n)==3){m <-9}
      if(length(n)==2){m <-5}
      if(length(n)==1){m <-2}
      #if(length(n)==1){stop("\n Please provide at least 2 treatments \n")}
      out <- NULL
      out$kriged.output <- matrix(0,nrow(grid.coords),m)
      for(i in 1:sub.replicate){
        data.ck <- NULL
        for(j in 1:length(n)){
          ck <- data[data[,4]==nms[j],]
          sub.no.samples <- round(((sub.percentage)/(100*length(n)))*nrow(ck))
          #browser()
          if(sub.no.samples>nrow(ck)){stop("\n Decrease the sub.percentage \n")}
          if(sub.no.samples <= 10){stop("\n Increase the sub.percentage \n")}
          set.seed(round(runif(1,1001,10000001)))
          df <- kmeans(ck[,1:2], sub.no.samples)
          data.ck <- rbind(data.ck,cbind(df$centers,tapply(ck[,3],df$cluster,mean),j))
          rm(df);rm(ck)
        }
        row.names(data.ck) <- NULL; data.ck <- data.frame(data.ck)
        names(data.ck) <- names(data)
        ck <- ._Global_fnc(data=data.ck,
                           grid.size=grid.size,
                           grid.coords=grid.coords,
                           shapefile=shapefile,
                           model=model,
                           plot.global=plot.global,
                           tol.site=tol.site,
                           ...)
        #for(j in 1:m){
        #  out$kriged.output[,j] <- apply(cbind(ck$kriged.output[,j],out$kriged.output[,j]),1,max,na.rm=TRUE)
        #}
        out$kriged.output <- out$kriged.output + ck$kriged.output
        setTxtProgressBar(pb, i)
      }
      close(pb)  # end progress bar 
      out <- list(kriged.output=out$kriged.output/sub.replicate,
                  est.range=ck$est.range,est.psill=ck$est.psill,est.sample=ck$est.sample,
                  grid.coordinates=ck$grid.coordinates,
                  model=ck$model,grid.size=ck$grid.size,shapefile=ck$shapefile,type="kmeans")
      #out <- list(kriged.output=out$kriged.output,grid.coordinates=ck$grid.coordinates,
      #            model=ck$model,grid.size=ck$grid.size,shapefile=ck$shapefile,type="kmeans")
    }
    else if(type=="boot"){
      pb <- txtProgressBar(min = 0, max = sub.replicate, style = 3)   # set progress bar
      n <- table(data[,4])
      nms <- names(table(data[,4]))
      if(length(n)==3){m <-9}
      if(length(n)==2){m <-5}
      if(length(n)==1){m <-2}
      #if(length(n)==1){stop("\n Please provide at least 2 treatments \n")}
      out <- NULL
      out$kriged.output <- matrix(0,nrow(grid.coords),m)
      for(i in 1:sub.replicate){
        data.ck <- NULL
        for(j in 1:length(n)){
          ck <- data[data[,4]==nms[j],]
          sub.no.samples <- round(((sub.percentage)/(100*length(n)))*nrow(ck))
          if(sub.no.samples>nrow(ck)){stop("\n Decrease the sub.no.samples \n")}
          if(sub.no.samples<=10){stop("\n Increase the sub.no.samples \n")}
          set.seed(round(runif(1,1001,10000001)))
          data.ck <- rbind(data.ck,ck[sample(nrow(ck),size=sub.no.samples),])
          rm(ck)
        }
        row.names(data.ck) <- NULL; data.ck <- data.frame(data.ck)
        names(data.ck) <- names(data)
        ck <- ._Global_fnc(data=data.ck,
                           grid.size=grid.size,
                           grid.coords=grid.coords,
                           shapefile=shapefile,
                           model=model,
                           plot.global=plot.global,
                           tol.site=tol.site,
                           ...)
        #for(j in 1:m){
        #  out$kriged.output[,j] <- apply(cbind(ck$kriged.output[,j],out$kriged.output[,j]),1,max,na.rm=TRUE)
        #}
        out$kriged.output <- out$kriged.output + ck$kriged.output
        setTxtProgressBar(pb, i)
      }
      close(pb)  # end progress bar 
      out <- list(kriged.output=out$kriged.output/sub.replicate,
                  est.range=ck$est.range,est.psill=ck$est.psill,est.sample=ck$est.sample,
                  grid.coordinates=ck$grid.coordinates,
                  model=ck$model,grid.size=ck$grid.size,shapefile=ck$shapefile,type="boot")
    }
    else if(type=="epoch"){
      n <- table(data[,4])
      nms <- names(table(data[,4]))
      if(length(n)==3){m <-9}
      if(length(n)==2){m <-5}
      if(length(n)==1){m <-2}
      out <- NULL
      out$kriged.output <- matrix(0,nrow(grid.coords),m)
      batch.size <- 10
      sub.replicate <- ceiling(sum(n)/(batch.size*length(n)))
      pb <- txtProgressBar(min = 0, max = sub.replicate, style = 3)   # set progress bar
      dat <- data
      print(sub.replicate)
      for(i in 1:sub.replicate){
        if(i==sub.replicate){
          data.ck <- dat
          row.names(data.ck) <- NULL; data.ck <- data.frame(data.ck)
          names(data.ck) <- names(data)
          ck <- ._Global_fnc(data=data.ck,
                             grid.size=grid.size,
                             grid.coords=grid.coords,
                             shapefile=shapefile,
                             model=model,
                             plot.global=plot.global,
                             tol.site=tol.site,
                             ...)
        }
        else{
          data.ck <- NULL
          for(j in 1:length(n)){
            ck <- dat[dat[,4]==nms[j],]
            #if(batch.size>nrow(ck)){batch.size<-nrow(ck)}
            data.ck <- rbind(data.ck,ck[sample(nrow(ck),size=batch.size),])
            rm(ck)
          }
          dat <- dat[!(row.names(dat)%in%row.names(data.ck)),]
          #row.names(data.ck) <- NULL; data.ck <- data.frame(data.ck)
          names(data.ck) <- names(data)
          ck <- ._Global_fnc(data=data.ck,
                             grid.size=grid.size,
                             grid.coords=grid.coords,
                             shapefile=shapefile,
                             model=model,
                             plot.global=plot.global,
                             tol.site=tol.site,
                             ...)
          #for(j in 1:m){
          #  out$kriged.output[,j] <- apply(cbind(ck$kriged.output[,j],out$kriged.output[,j]),1,max,na.rm=TRUE)
          #}
        }
        #browser()
        #print(i)
        out$kriged.output <- out$kriged.output + ck$kriged.output
        setTxtProgressBar(pb, i)
      }
      #browser()
      close(pb)  # end progress bar 
      out <- list(kriged.output=out$kriged.output/sub.replicate,
                  est.range=ck$est.range,est.psill=ck$est.psill,est.sample=ck$est.sample,
                  grid.coordinates=ck$grid.coordinates,
                  model=ck$model,grid.size=ck$grid.size,shapefile=ck$shapefile,type="boot")
    }
    else{
      stop("\n Define model correctly: global, mixed or local \n")
    }
    end.time <- proc.time()[3]
    t <- end.time-start.time
    out$comp.time <- .fnc.time_(t)
	#
	# check the missing values
	#
    # infill with average smooth for missing values
    # 8 adjacent grids are used in this context
    #
	if(length(unlist(out$kriged.output[complete.cases(out$kriged.output),]))==length(unlist(out$kriged.output))){
      out$kriged.output <- out$kriged.output	
	}
	else{
     check <- as.data.frame(out$kriged.output)
     s <- as.numeric(row.names(check[!complete.cases(check),]))
     d.check <- rdist(out$grid.coordinates)
     #d.check <- d.check[s,]
     for(i in 1:length(s)){
       ss <- which(c(d.check[s[i],]) <= sort(d.check[s[i],])[9]+1)
       check[s[i],] <- apply(check[ss[!ss%in%s[i]],],2,mean,na.rm=TRUE)
     }
     rm(d.check); rm(s); rm(ss);
     out$kriged.output <- as.matrix(check)
	}
	#
    out
  }
##
##
._Global_fnc <-
  function(data,
           grid.size,
           grid.coords,
           shapefile,
           model,
           plot.global,
           tol.site,
           ...) {
    #function(data = data,
    #         grid.size = NULL,
    #         grid.coords = NULL,
    #         shapefile = NULL,
    #         model = "Exp",
    #         plot.global = FALSE,
    #         tol.site = 1000,
    #         ...) {
    #
    # grid.size = user defined grid.size for kriging, format c(10,10), ie, 10x10 grid 
    # grid.coords = user defined coordinate points
    # shapefile = user defined shapefile for kriging
    # model =  "Exp", "Sph", "Gau"
    # plot.global = if TRUE, plot variograms
    #
    if (!model %in% c("Exp", "Sph", "Gau")) {
      stop("\n Define model correctly: Exp, Sph or Gau \n")
    }
    #
    data <- data[order(data[, 4]), ]
    ll <- unique(data[, 4])
    tr <- length(unique(data[, 4]))
    if (tr > 3) {
      stop("\n Cann't take more than 3 treatments \n")
    }
    ck <- NULL
    for (i in 1:tr) {
      ck[i] <- length(data[data[, 4] == ll[i], 4])
    }
    coords <- as.matrix(data[, 1:2])
    dimnames(coords) <- NULL
    #
    x <- range(coords[, 1])
    y <- range(coords[, 2])
    if (is.null(grid.size) &
        is.null(grid.coords) & is.null(shapefile)) {
      stop("\n Provide a value for the argument grid.size, grid.coords or shapefile \n")
    }
    else if (!is.null(grid.size)) {
      gr <- spT.grid.coords(x, y, by = grid.size)
    }
    else if (!is.null(grid.coords)) {
      gr <- as.matrix(grid.coords)
    }
    else if (!is.null(shapefile)) {
      gr <- as.matrix(coordinates(shapefile))
    }
    else {
      stop("\n Provide a value for the argument grid.size, grid.coords or shapefile \n")
    }
    dimnames(gr) <- NULL
    # check the big-n problem
    if(nrow(data) > tol.site) {
      cat("\n For each treatment max tol.site = ",tol.site)
      stop("\n Model stopped due to the big-n problem, use the Local Kriging or check the tol.site argument \n")
    }
    # covariance function and kriging/cokriging
    if (tr == 1) {
      result <- .TR_1(
        data = data,
        grid = gr,
        model = model
      )
    }
    if (tr == 2) {
      result <- .TR_2(
        data = data,
        grid = gr,
        model = model,
        tr = tr
      )
    }
    if (tr == 3) {
      result <- .TR_3(
        data = data,
        grid = gr,
        model = model,
        tr = tr
      )
    }
    dimnames(gr)[[2]] <- names(data)[1:2]
    result <-
      list(
        kriged.output = as.data.frame(result[c(1:(length(result)-2))]),
        est.parameters = result$range_psill,
        est.sample = result$n.sample,
        grid.coordinates = gr,
        model = model,
        grid.size = grid.size,
        shapefile = shapefile,
        type="global"
      )
    if(tr == 1){
      names(result$kriged.output) <-
        c("tr.pred","tr.se")
    }	
    if(tr == 2){
      names(result$kriged.output) <-
        c("tr.01.pred","tr.01.se","tr.02.pred","tr.02.se","tr.12.se")
    }	
    if(tr == 3){
      names(result$kriged.output) <-
        c("tr.01.pred","tr.01.se","tr.02.pred","tr.02.se","tr.03.pred","tr.03.se","tr.12.se","tr.13.se","tr.23.se")
    }	
    class(result) <- "cokriging"
    result
    #
  }
##
##
._Local_fnc <-
  function(data,
           model,
           grid.size,
           grid.coords,
           shapefile,
           block.size,
           plot.local,
           tol.site,
           ...) {
    #
    # grid.size = user defined grid.size for kriging, format c(10,10), ie, 10x10 grid 
    # grid.coords = user defined coordinate points
    # shapefile = user defined shapefile for kriging
    #
    # model =  "Exp", "Sph", "Gau"
    #
    # block.size => to be defined by user (default is a function of: (1) max-distance (2) range (3) no. of spatial points)
    # i.e., block.size = f(phi,maxd,n); phi = range, maxd = max-distance, n = no. of spatial points.
    # f(phi,maxd,n) = phi * (n/maxd)^(-1), if (n/maxd)^(-1) > 1
    #               = phi, otherwise
    #
    # For big-n problem: block.size = f(maxd,tol.site,n), i.e., block.size  <- max(c(d))*(tol.site/nrow(d))
    #
    # plot.local = TRUE will return the local variograms for each kriging points.
    #
    # tol.site = maximum number of observation locations to fit a global model
    #
    if (!model %in% c("Exp", "Sph", "Gau")) {
      stop("\n Define model correctly: Exp, Sph or Gau \n")
    }
    #
    data <- data[order(data[, 4]), ]
    ll <- unique(data[, 4])
    tr <- length(unique(data[, 4]))
    if (tr > 3) {
      stop("\n Cann't take more than 3 treatments \n")
    }
    ck <- NULL
    for (i in 1:tr) {
      ck[i] <- length(data[data[, 4] == ll[i], 4])
    }
    coords <- as.matrix(data[, 1:2])
    dimnames(coords) <- NULL
    #
    if (is.null(grid.size) &
        is.null(grid.coords) & is.null(shapefile)) {
      stop("\n Provide a value for the argument grid.size, grid.coords or shapefile \n")
    }
    else if (!is.null(grid.size)) {
      x <- range(coords[, 1])
      y <- range(coords[, 2])
      gr <- spT.grid.coords(x, y, by = grid.size)
    }
    else if (!is.null(grid.coords)) {
      gr <- as.matrix(grid.coords)
    }
    else if (!is.null(shapefile)) {
      gr <- as.matrix(coordinates(shapefile))
    }
    else {
      stop("\n Provide a value for the argument grid.size, grid.coords or shapefile \n")
    }
    dimnames(gr) <- NULL
    d <- rdist(coords)
    d.gr <- rdist(coords, gr) # rdist is from fields package
    # check big-n problem
    if(nrow(data) > tol.site) {
      print(paste0("Number of data point exceeds 'tol.site=",tol.site,"'. Initiates the big-n problem."))
    }
    #
    result <- ._local_fnc_bign(data=data,gr=gr,model=model,tr=tr,ck=ck,d=d,d.gr=d.gr,tol.site=tol.site,block.size=block.size,plot.local=plot.local)
    #
    result <-
      list(
        kriged.output = result$result$kriged.output,
        est.parameters = result$result$est.parameters,
        est.sample = result$result$est.sample,
        neighbourhood.size = result$block.size,
        grid.coordinates = gr,
        model = model,
        grid.size = grid.size,
        shapefile = shapefile,
        type="local-adaptive"
      )
    class(result) <- "cokriging"
    result
  }
##
##
._Local_fnc_processed <-
  function(data,
           model,
           grid.size,
           grid.coords,
           shapefile,
           block.size,
           plot.local,
           tol.site,
           ...) {
    #
    # grid.size = user defined grid.size for kriging, format c(10,10), ie, 10x10 grid 
    # grid.coords = user defined coordinate points
    # shapefile = user defined shapefile for kriging
    #
    # model =  "Exp", "Sph", "Gau"
    #
    # block.size => to be defined by user (default is a function of: (1) max-distance (2) range (3) no. of spatial points)
    # i.e., block.size = f(phi,maxd,n); phi = range, maxd = max-distance, n = no. of spatial points.
    # f(phi,maxd,n) = phi * (n/maxd)^(-1), if (n/maxd)^(-1) > 1
    #               = phi, otherwise
    #
    # For big-n problem: block.size = f(maxd,tol.site,n), i.e., block.size  <- max(c(d))*(tol.site/nrow(d))
    #
    # plot.local = TRUE will return the local variograms for each kriging points.
    #
    # tol.site = maximum number of observation locations to fit a global model
    #
    if (!model %in% c("Exp", "Sph", "Gau")) {
      stop("\n Define model correctly: Exp, Sph or Gau \n")
    }
    #
    library(sp)
    library(spTimer)
    library(gstat)
    library(fields)
    data <- data[order(data[, 4]), ]
    ll <- unique(data[, 4])
    tr <- length(unique(data[, 4]))
    if (tr > 3) {
      stop("\n Cann't take more than 3 treatments \n")
    }
    ck <- NULL
    for (i in 1:tr) {
      ck[i] <- length(data[data[, 4] == ll[i], 4])
    }
    coords <- as.matrix(data[, 1:2])
    dimnames(coords) <- NULL
    #
    if (is.null(grid.size) &
        is.null(grid.coords) & is.null(shapefile)) {
      stop("\n Provide a value for the argument grid.size, grid.coords or shapefile \n")
    }
    else if (!is.null(grid.size)) {
      x <- range(coords[, 1])
      y <- range(coords[, 2])
      gr <- spT.grid.coords(x, y, by = grid.size)
    }
    else if (!is.null(grid.coords)) {
      gr <- as.matrix(grid.coords)
    }
    else if (!is.null(shapefile)) {
      gr <- as.matrix(coordinates(shapefile))
    }
    else {
      stop("\n Provide a value for the argument grid.size, grid.coords or shapefile \n")
    }
    dimnames(gr) <- NULL
    d <- rdist(coords)
    d.gr <- rdist(coords, gr) # rdist is from fields package
    #
    result <- ._local_fnc_bign_processed(data=data,gr=gr,model=model,tr=tr,ck=ck,d=d,d.gr=d.gr,tol.site=tol.site,block.size=block.size,plot.local=plot.local)
    #
    result <-
      list(
        kriged.output = result$result$kriged.output,
        est.parameters = result$result$est.parameters,
        est.sample = result$result$est.sample,
        neighbourhood.size = result$block.size,
        grid.coordinates = gr,
        model = model,
        grid.size = grid.size,
        shapefile = shapefile,
        type="local-processed"
      )
    class(result) <- "cokriging"
    result
  }
##
##
._local_fnc_bign <- function(data,gr,model,tr,ck,d,d.gr,tol.site,block.size,plot.local){
  #
  result <- list()
  if (tr == 1) {
    result$kriged.output <- matrix(NA, nrow = ncol(d.gr), ncol = 2)
    dimnames(result$kriged.output)[[2]] <- c("tr.pred","tr.var")
    result$est.parameters <- list()
    result$est.sample <- matrix(NA, nrow = ncol(d.gr), ncol = tr)
    tt <- 5
    #tt <- 1
  }
  if (tr == 2) {
    result$kriged.output <- matrix(NA, nrow = ncol(d.gr), ncol = 5)
    dimnames(result$kriged.output)[[2]] <- c("tr.01.pred","tr.01.var","tr.02.pred","tr.02.var","tr.12.cov")
    result$est.parameters <- list()
    result$est.sample <- matrix(NA, nrow = ncol(d.gr), ncol = tr)
    tt <- 5*tr
    #tt <- 1
  }
  if (tr == 3) {
    result$kriged.output <- matrix(NA, nrow = ncol(d.gr), ncol = 9)
    dimnames(result$kriged.output)[[2]] <- c("tr.01.pred","tr.01.var","tr.02.pred","tr.02.var","tr.03.pred","tr.03.var","tr.12.cov","tr.13.cov","tr.23.cov")
    result$est.parameters <- list()
    result$est.sample <- matrix(NA, nrow = ncol(d.gr), ncol = tr)
    tt <- 5*tr
    #tt <- 1
  }
  #
  # dynamic block size 
  #
  if (is.null(block.size)) {
    if(nrow(d)>tol.site){
      set.seed(1234)
      #dmin <- quantile(d[sample(x=1:nrow(d),size=10),],0.05)
      dmin <- quantile(d[sample(x=1:nrow(d),size=10),],tt/nrow(d))
      increment <- sqrt((tr*max(max(d.gr)^2/ck)+pi*dmin^2)/pi)-dmin
      block.size <- dmin
      #browser()
      print(paste0("To address the big-n problem, we define initial 'neighbourhood.size' as: ",round(block.size,2)))
      print(paste0("The increment factor is estimated as: ",round(increment,2)))
      print(paste0("Please IGNORE any WARNINGS"))
    }
    else{
      #dmin <- quantile(d[sample(x=1:nrow(d),size=10),],0.05)
      dmin <- quantile(d[sample(x=1:nrow(d),size=10),],tt/nrow(d))
      increment <- sqrt((tr*max(max(d.gr)^2/ck)+pi*dmin^2)/pi)-dmin
      block.size <- dmin
      #browser()
      print(paste0("Initial 'neighbourhood.size' is defined as: ",round(block.size,2)))
      print(paste0("The increment factor is estimated as: ",round(increment,2)))
      print(paste0("Please IGNORE any WARNINGS"))
      #browser()
    }
  }
  else{
    dmin <- block.size
    increment <- sqrt((tr*(pi/4)*max(max(d.gr)^2/ck)+pi*dmin^2)/pi)-dmin
    block.size <- dmin
    print(paste0("Initial 'neighbourhood.size' is defined as: ",round(block.size,2)))
    print(paste0("The increment factor is estimated as: ",round(increment,2)))
    print(paste0("Please IGNORE any WARNINGS"))
  }
  #
  pb <-
    txtProgressBar(min = 0,
                   max = ncol(d.gr),
                   style = 3)   # set progress bar
  #
  store.block <- block.size
  store.block.size <- NULL
  if (plot.local == TRUE) {
    print("Error: 'plot.local' option is not avaiable for big-n problem")
  }
  #
  for (i in 1:ncol(d.gr)) { 
    print(paste0("Counter adaptive: ",i))
    #browser()
    block.size <- .wrapper_check_bign(data=data,model=model,tr=tr,tmp=d.gr[,i],block.size=store.block[1],increment=increment)
    #browser()
    #print(paste0("store.block.size : ",round(store.block.size[i],2)))
    tmp <- which(d.gr[, i] <= block.size)
    dat <-  data[tmp, ]
    if(nrow(dat) <= (tr*20)){ # ensuring minimum (20*tr) observations in the small data  
      # use repeat function 
      ##
      j <- 0
      repeat{
        j <- j+1
        block.size <- block.size + increment
        tmp <- which(d.gr[, i] <= block.size)
        if (length(tmp) >= tr*20) {      
          break
        }
      }
      rm(j)
      dat <-  data[tmp, ]
    }
    #browser()
    #print(paste0("dim-data : ",dim(dat)))
    store.block.size <- c(store.block.size,block.size)
    #print(paste0("store.block.size : ",round(store.block.size[i],2)))
    tr.ck <- length(unique(dat[, 4]))
    ll <- unique(dat[, 4])
    ck.new <- NULL
    for (k in 1:tr.ck) {
      ck.new[k] <- length(dat[dat[, 4] == ll[k], 4])
    }
    #browser()
    ##
    if (tr == 1) {
      re <- try(.TR_1(
        data = dat,
        grid = gr[i,],
        model = model
      ), TRUE)
      if (class(re) == "try-error") {
        ree <- .try_processed_TR1(i=i, data=data, grid=gr, model=model, tr=tr, ck=ck, d=d, d.gr=d.gr, block.size)
        re <- ree$out
        store.block.size[i] <- ree$block.size
      }
      result$kriged.output[i, ] <- unlist(re[c(1:(length(re)-2))])
      result$est.parameters[[i]] <- re$range_psill
      result$est.sample[i,] <- re$n.sample
    }
    if (tr == 2) {
      re <- try(.TR_2(
        data = dat,
        grid = gr[i,],
        model = model,
        tr = tr.ck
      ), TRUE)
      if (class(re) == "try-error") {
        ree <- .try_processed_TR2(i=i, data=data, grid=gr, model=model, tr=tr, ck=ck, d=d, d.gr=d.gr, block.size)
        re <- ree$out
        store.block.size[i] <- ree$block.size
      }
      result$kriged.output[i, ] <- unlist(re[c(1:(length(re)-2))])
      result$est.parameters[[i]] <- re$range_psill
      result$est.sample[i,] <- re$n.sample
    }
    if (tr == 3) {
      #browser()
      re <- try(.TR_3(
        data = dat,
        grid = gr[i,],
        model = model,
        tr = tr.ck
      ), TRUE)
      if (class(re) == "try-error") {
        ree <- .try_processed_TR3(i=i, data=data, grid=gr, model=model, tr=tr, ck=ck, d=d, d.gr=d.gr, block.size)
        re <- ree$out
        store.block.size[i] <- ree$block.size
      }
      result$kriged.output[i, ] <- unlist(re[c(1:(length(re)-2))])
      result$est.parameters[[i]] <- re$range_psill
      result$est.sample[i,] <- re$n.sample
    }
    setTxtProgressBar(pb, i)
  }
  close(pb)
  list(result=result,block.size=store.block.size)
}
##
##
._local_fnc_bign_processed <- function(data,gr,model,tr,ck,d,d.gr,tol.site,block.size,plot.local){
  #
  result <- list()
  if (tr == 1) {
    result$kriged.output <- matrix(NA, nrow = ncol(d.gr), ncol = 2)
    dimnames(result$kriged.output)[[2]] <- c("tr.pred","tr.var")
    result$est.parameters <- list()
    result$est.sample <- matrix(NA, nrow = ncol(d.gr), ncol = tr)
    tt <- 5
    #tt <- 1
  }
  if (tr == 2) {
    result$kriged.output <- matrix(NA, nrow = ncol(d.gr), ncol = 5)
    dimnames(result$kriged.output)[[2]] <- c("tr.01.pred","tr.01.var","tr.02.pred","tr.02.var","tr.12.cov")
    result$est.parameters <- list()
    result$est.sample <- matrix(NA, nrow = ncol(d.gr), ncol = tr)
    tt <- 5*tr
    #tt <- 1
  }
  if (tr == 3) {
    result$kriged.output <- matrix(NA, nrow = ncol(d.gr), ncol = 9)
    dimnames(result$kriged.output)[[2]] <- c("tr.01.pred","tr.01.var","tr.02.pred","tr.02.var","tr.03.pred","tr.03.var","tr.12.cov","tr.13.cov","tr.23.cov")
    result$est.parameters <- list()
    result$est.sample <- matrix(NA, nrow = ncol(d.gr), ncol = tr)
    tt <- 5*tr
    #tt <- 1
  }
  #
  pb <-
    txtProgressBar(min = 0,
                   max = ncol(d.gr),
                   style = 3)   # set progress bar
  #
  if (plot.local == TRUE) {
    print("Warnings: 'plot.local' option is not avaiable for big-n problem")
  }
  #
  store.block.size <- NULL
  #
  for (i in 1:ncol(d.gr)) { 
    print(paste0("Counter processed: ",i))
    #browser()
    #cat(i,"-")
    #tmp <- cbind(1:nrow(d.gr), d.gr) # tmp[,c(1,i+1)]
    #tmp <- c(tmp[tmp[, i + 1] <= block.size, 1])
    tmp <- which(d.gr[, i] <= block.size[i])
    if(length(tmp)==0){
      block.size[i] <- sort(d.gr[, i])[2]
      tmp <- which(d.gr[, i] <= block.size[i])
    }
    dat <-  data[tmp, ]
    #browser()
    tr.ck <- length(unique(dat[, 4]))
    # ensure all treatments are in the new dataset 
    if(tr.ck < tr){
      dmin <- min(block.size)
      increment <- sqrt((tr*(pi/4)*max(max(d.gr)^2/ck)+pi*dmin^2)/pi)-dmin
      j <- 0
      repeat{
        j <- j+1
        block.size[i] <- block.size[i] + increment
        tmp <- which(d.gr[, i] <= block.size[i])
        dat <-  data[tmp, ]
        tr.ck <- length(unique(dat[, 4]))
        if (tr.ck == tr) {      
          break
        }
      }
      rm(j)
    }
    #
    ll <- unique(dat[, 4])
    ck.new <- NULL
    for (k in 1:tr.ck) {
      ck.new[k] <- length(dat[dat[, 4] == ll[k], 4])
    }
    # ensuring at least 5 points for each treatment
    if(min(ck.new) < 5){
      dmin <- min(block.size)
      increment <- sqrt((tr*(pi/4)*max(max(d.gr)^2/ck)+pi*dmin^2)/pi)-dmin
      j <- 0
      repeat{
        j <- j+1
        block.size[i] <- block.size[i] + increment
        tmp <- which(d.gr[, i] <= block.size[i])
        dat <-  data[tmp, ]
        tr.ck <- length(unique(dat[, 4]))
        ll <- unique(dat[, 4])
        ck.new <- NULL
        for (k in 1:tr.ck) {
          ck.new[k] <- length(dat[dat[, 4] == ll[k], 4])
        }
        if (min(ck.new) >= 5) {      
          break
        }
      }
      rm(j)
    }
    #
    store.block.size[i] <- block.size[i]
    #print(paste0("dim of local data:",nrow(dat)))
    #print(paste0("store.block.size:",store.block.size[i]))    
    #browser()
    ##
    if (tr == 1) {
      re <- try(.TR_1(
        data = dat,
        grid = gr[i,],
        model = model
      ), TRUE)
      if (class(re) == "try-error") {
        ree <- .try_processed_TR1(i=i, data=data, grid=gr, model=model, tr=tr, ck=ck, d=d, d.gr=d.gr, block.size[i])
        re <- ree$out
        store.block.size[i] <- ree$block.size
      }
      result$kriged.output[i, ] <- unlist(re[c(1:(length(re)-2))])
      result$est.parameters[[i]] <- re$range_psill
      result$est.sample[i,] <- re$n.sample
    }
    if (tr == 2) {
      re <- try(.TR_2(
        data = dat,
        grid = gr[i,],
        model = model,
        tr = tr.ck
      ), TRUE)
      if (class(re) == "try-error") {
        ree <- .try_processed_TR2(i=i, data=data, grid=gr, model=model, tr=tr, ck=ck, d=d, d.gr=d.gr, block.size[i])
        re <- ree$out
        store.block.size[i] <- ree$block.size
      }
      result$kriged.output[i, ] <- unlist(re[c(1:(length(re)-2))])
      result$est.parameters[[i]] <- re$range_psill
      result$est.sample[i,] <- re$n.sample
    }
    if (tr == 3) {
      #browser()
      re <- try(.TR_3(
        data = dat,
        grid = gr[i,],
        model = model,
        tr = tr.ck
      ), TRUE)
      if (class(re) == "try-error") {
        #browser()
        ree <- .try_processed_TR3(i=i, data=data, grid=gr, model=model, tr=tr, ck=ck, d=d, d.gr=d.gr, block.size[i])
        re <- ree$out
        store.block.size[i] <- ree$block.size
      }
      result$kriged.output[i, ] <- unlist(re[c(1:(length(re)-2))])
      result$est.parameters[[i]] <- re$range_psill
      result$est.sample[i,] <- re$n.sample
    }
    setTxtProgressBar(pb, i)
  }
  close(pb)
  list(result=result,block.size=store.block.size)
}
##
## function inside try-error for local-processed
.try_processed_TR1 <- function(i, data, grid, model, tr, ck, d, d.gr, block.size){
  tt <- 5
  #tt <- 1
  #dmin <- quantile(d[sample(x=1:nrow(d),size=10),],0.05)
  dmin <- quantile(d[sample(x=1:nrow(d),size=10),],tt/nrow(d))
  #increment <- sqrt((tr*(pi/4)*max(max(d.gr)^2/ck)+pi*dmin^2)/pi)-dmin
  increment <- sqrt((tr*max(max(d.gr)^2/ck)+pi*dmin^2)/pi)-dmin
  block.size0 <- .wrapper_check_bign(data=data,model=model,tr=tr,tmp=d.gr[,i],block.size=block.size[i],increment=increment)
  #print(block.size0)
  tmp <- which(d.gr[, i] <= block.size0)
  dat <-  data[tmp, ]
  out <- NULL
  out$block.size <- block.size0
  out$out <- .TR_1(
    data = dat,
    grid = gr[i,],
    model = model
  )
  out
}
##
##
.try_processed_TR2 <- function(i, data, grid, model, tr, ck, d, d.gr, block.size){
  tt <- 5*tr
  #tt <- 1
  #dmin <- quantile(d[sample(x=1:nrow(d),size=10),],0.05)
  dmin <- quantile(d[sample(x=1:nrow(d),size=10),],tt/nrow(d))
  #increment <- sqrt((tr*(pi/4)*max(max(d.gr)^2/ck)+pi*dmin^2)/pi)-dmin
  increment <- sqrt((tr*max(max(d.gr)^2/ck)+pi*dmin^2)/pi)-dmin
  block.size0 <- .wrapper_check_bign(data=data,model=model,tr=tr,tmp=d.gr[,i],block.size=block.size[i],increment=increment)
  #print(block.size0)
  tmp <- which(d.gr[, i] <= block.size0)
  dat <-  data[tmp, ]
  tr.ck <- length(unique(dat[, 4]))
  ll <- unique(dat[, 4])
  ck.new <- NULL
  for (k in 1:tr.ck) {
    ck.new[k] <- length(dat[dat[, 4] == ll[k], 4])
  }
  out <- NULL
  out$block.size <- block.size0
  out$out <- .TR_2(
    data = dat,
    grid = grid[i,],
    model = model,
    tr = tr.ck
  )
  out
}
##
##
.try_processed_TR3 <- function(i, data, grid, model, tr, ck, d, d.gr, block.size){
  tt <- 5*tr
  #tt <- 1
  #dmin <- quantile(d[sample(x=1:nrow(d),size=10),],0.05)
  dmin <- quantile(d[sample(x=1:nrow(d),size=10),],tt/nrow(d))
  increment <- sqrt((tr*max(max(d.gr)^2/ck)+pi*dmin^2)/pi)-dmin
  #browser()
  block.size0 <- .wrapper_check_bign(data=data,model=model,tr=tr,tmp=d.gr[,i],block.size=block.size[i],increment=increment)
  #print(block.size0)
  tmp <- which(d.gr[, i] <= block.size0)
  dat <-  data[tmp, ]
  tr.ck <- length(unique(dat[, 4]))
  ll <- unique(dat[, 4])
  ck.new <- NULL
  for (k in 1:tr.ck) {
    ck.new[k] <- length(dat[dat[, 4] == ll[k], 4])
  }
  out <- NULL
  out$block.size <- block.size0
  out$out <- .TR_3(
    data = dat,
    grid = grid[i,],
    model = model,
    tr = tr.ck
  )
  out
}
################
## sub-routines
################
##
##
.wrapper_cov <- function(data, model) {
  dat <- data
  coordinates(dat) <-
    as.formula(paste0("~", names(data)[1], "+", names(data)[2]))
  v0 <- variogram(as.formula(paste0(names(data)[3], "~1")), data = dat)
  v <- fit.variogram(v0, vgm(model = model))
  v
}
##
##
.wrapper_check_bign <- function(data,model,tr,tmp,block.size,increment=NULL){
  if(is.null(increment)){
    #increment.factor <- c(seq(1.0,2,0.1),seq(2.1,3,0.1),seq(3.1,4,0.1),seq(4.1,5,0.1),seq(5.1,6,0.1),
    #                      seq(6.1,7,0.1),seq(7.1,8,0.1),seq(8.1,9,0.1),seq(9.1,10,0.1))
    increment.factor <- c(seq(1.0,10,0.1))
  }
  else{
    increment.factor <- c(0,rep(increment,99)*1:99)
  }
  #  
  options(warn=-1)
  .wrapper_check_internal <- function(data, model,tr) {
    ll <- unique(data[, 4])
    if(tr ==1){
      dat <- data
      coordinates(dat) <-
        as.formula(paste0("~", names(data)[1], "+", names(data)[2]))
      v0 <- variogram(as.formula(paste0(names(data)[3], "~1")), data = dat)
      v <- fit.variogram(v0, vgm(model = model))
      rm(v0); rm(v); rm(dat)
    }
    else if (tr == 2) {
      dat <- data[data[, 4] == ll[1], ]
      coordinates(dat) <-
        as.formula(paste0("~", names(data)[1], "+", names(data)[2]))
      v01 <-
        variogram(as.formula(paste0(names(data)[3], "~1")), data = dat)
      v1 <- fit.variogram(v01, vgm(model = model))
      dat <- data[data[, 4] == ll[2], ]
      coordinates(dat) <-
        as.formula(paste0("~", names(data)[1], "+", names(data)[2]))
      v02 <-
        variogram(as.formula(paste0(names(data)[3], "~1")), data = dat)
      v2 <- fit.variogram(v02, vgm(model = model))
      rm(v01); rm(v1); rm(v02); rm(v2); rm(dat);
      #
      dat <- data
      g.dat <- list()
      g.dat[[1]] <- subset(dat, dat[,4]==ll[1])
      names(g.dat[[1]])[3] <- paste0(names(g.dat[[1]])[3],ll[1])
      coordinates(g.dat[[1]]) <-as.formula(paste0("~", names(g.dat[[1]])[1], "+", names(g.dat[[1]])[2]))
      g.dat[[2]] <- subset(dat, dat[,4]==ll[2])
      names(g.dat[[2]])[3] <- paste0(names(g.dat[[2]])[3],ll[2])
      coordinates(g.dat[[2]]) <-as.formula(paste0("~", names(g.dat[[2]])[1], "+", names(g.dat[[2]])[2]))
      g <- gstat(id="tr1",formula=as.formula(paste0(names(g.dat[[1]])[1], "~1")),data=g.dat[[1]],set = list(nocheck = 1))
      g <- gstat(g,id="tr2",formula=as.formula(paste0(names(g.dat[[2]])[1], "~1")),data=g.dat[[2]],set = list(nocheck = 1))
      rm(g.dat); rm(dat)
      v0 <- variogram(g)
      v <- fit.lmc(v=v0, g=g, vgm(model = model))
      rm(g); rm(v0); rm(v);   
    }
    else if (tr == 3) {
      dat <- data[data[, 4] == ll[1], ]
      coordinates(dat) <-
        as.formula(paste0("~", names(data)[1], "+", names(data)[2]))
      v01 <-
        variogram(as.formula(paste0(names(data)[3], "~1")), data = dat)
      v1 <- fit.variogram(v01, vgm(model = model))
      dat <- data[data[, 4] == ll[2], ]
      coordinates(dat) <-
        as.formula(paste0("~", names(data)[1], "+", names(data)[2]))
      v02 <-
        variogram(as.formula(paste0(names(data)[3], "~1")), data = dat)
      v2 <- fit.variogram(v02, vgm(model = model))
      dat <- data[data[, 4] == ll[3], ]
      coordinates(dat) <-
        as.formula(paste0("~", names(data)[1], "+", names(data)[2]))
      v03 <-
        variogram(as.formula(paste0(names(data)[3], "~1")), data = dat)
      v3 <- fit.variogram(v03, vgm(model = model))
      dat <- data[data[, 4] == ll[1] | data[, 4] == ll[2], ]
      coordinates(dat) <-
        as.formula(paste0("~", names(data)[1], "+", names(data)[2]))
      v012 <-
        variogram(as.formula(paste0(names(data)[3], "~1")), data = dat)
      v12 <- fit.variogram(v012, vgm(model = model))
      dat <- data[data[, 4] == ll[1] | data[, 4] == ll[3], ]
      coordinates(dat) <-
        as.formula(paste0("~", names(data)[1], "+", names(data)[2]))
      v013 <-
        variogram(as.formula(paste0(names(data)[3], "~1")), data = dat)
      v13 <- fit.variogram(v013, vgm(model = model))
      dat <- data[data[, 4] == ll[2] | data[, 4] == ll[3], ]
      coordinates(dat) <-
        as.formula(paste0("~", names(data)[1], "+", names(data)[2]))
      v023 <-
        variogram(as.formula(paste0(names(data)[3], "~1")), data = dat)
      v23 <- fit.variogram(v023, vgm(model = model))
      rm(v01); rm(v1); rm(v02); rm(v2); rm(v023); rm(v3); rm(v012); rm(v12); rm(v013); rm(v13); rm(v023); rm(v23); rm(dat)
      #
      dat <- data
      g.dat <- list()
      g.dat[[1]] <- subset(dat, dat[,4]==ll[1])
      names(g.dat[[1]])[3] <- paste0(names(g.dat[[1]])[3],ll[1])
      coordinates(g.dat[[1]]) <-as.formula(paste0("~", names(g.dat[[1]])[1], "+", names(g.dat[[1]])[2]))
      g.dat[[2]] <- subset(dat, dat[,4]==ll[2])
      names(g.dat[[2]])[3] <- paste0(names(g.dat[[2]])[3],ll[2])
      coordinates(g.dat[[2]]) <-as.formula(paste0("~", names(g.dat[[2]])[1], "+", names(g.dat[[2]])[2]))
      g.dat[[3]] <- subset(dat, dat[,4]==ll[3])
      names(g.dat[[3]])[3] <- paste0(names(g.dat[[3]])[3],ll[3])
      coordinates(g.dat[[3]]) <-as.formula(paste0("~", names(g.dat[[3]])[1], "+", names(g.dat[[3]])[2]))
      g <- gstat(id="tr1",formula=as.formula(paste0(names(g.dat[[1]])[1], "~1")),data=g.dat[[1]],set = list(nocheck = 1))
      g <- gstat(g,id="tr2",formula=as.formula(paste0(names(g.dat[[2]])[1], "~1")),data=g.dat[[2]],set = list(nocheck = 1))
      g <- gstat(g,id="tr3",formula=as.formula(paste0(names(g.dat[[3]])[1], "~1")),data=g.dat[[3]],set = list(nocheck = 1))
      rm(g.dat); rm(dat)
      v0 <- variogram(g)
      v <- fit.lmc(v=v0, g=g, vgm(model = model))
      rm(g); rm(v0); rm(v);   
    }
    else{
      stop("\n Treatments should be <= 3. \n")
    }
  }
  ##
  .internal_fnc <- function(data,model,tr,tmp,block.size){
    wp <- which(c(tmp) <= block.size)
    if(length(wp)==0){
      block.size <- sort(c(tmp))[2]
      wp <- which(c(tmp) <= block.size)
    }
    wp <- .wrapper_check_internal(data=data[wp,], model=model, tr=tr)
    wp
  }
  ##
  j <- 0
  repeat{
    j <- j+1
    block.size0 <- block.size + increment.factor[j]
    #print(j)
    #print(block.size0)
    #print(increment.factor[j])
    bign.check <- try(.internal_fnc(data=data,model=model,tr=tr,tmp=tmp,block.size=block.size0),TRUE)
    #if (class(bign.check) == "numeric") {
    if (class(bign.check)=="NULL") {      
      #print(block.size0)
      #print(j)
      break
    }
  }
  #print(block.size0)
  block.size0
}		
##
##
.TR_1 <- function(data, model, d, d.gr) {
  g.dat <- as.data.frame(data)
  coordinates(g.dat) <- as.formula(paste0("~", names(g.dat)[1], "+", names(g.dat)[2]))
  v0 <- variogram(as.formula(paste0(names(g.dat)[1], "~1")),g.dat)
  v <- fit.variogram(v0,model=vgm(model=model))
  if(is.matrix(grid) | is.data.frame(grid)){
    grid <- as.data.frame(grid)
    coordinates(grid) <- names(grid)
  }
  else{
    grid <- data.frame(matrix(c(grid),1,2))
    coordinates(grid) <- names(grid)
  }
  out <- krige(formula=as.formula(paste0(names(g.dat)[1], "~1")),g.dat, grid, model=v)
  list(out.pred = out$var1.pred, out.var = out$var1.var, range_psill=v, n.sample=nrow(data))
}
##
##
.TR_2 <- function(data, grid, model, tr) {
  g.dat <- list()
  ll <- unique(data[, 4])
  for(j in 1:tr){
    g.dat[[j]] <- subset(data,data[,4]==ll[j])
    names(g.dat[[j]])[3] <- paste0(names(g.dat[[j]])[3],ll[j])
    coordinates(g.dat[[j]]) <-
      as.formula(paste0("~", names(g.dat[[j]])[1], "+", names(g.dat[[j]])[2]))
  }
  g <- gstat(id="tr1",formula=as.formula(paste0(names(g.dat[[1]])[1], "~1")),data=g.dat[[1]],set = list(nocheck = 1))
  g <- gstat(g,id="tr2",formula=as.formula(paste0(names(g.dat[[2]])[1], "~1")),data=g.dat[[2]],set = list(nocheck = 1))
  rm(g.dat)
  ck <- NULL
  for (i in 1:tr) {
    ck[i] <- length(data[data[, 4] == ll[i], 4])
  }
  (max.dist <- max(c(rdist(data[,1:2])))*propMaxD);  
  v0 <- variogram(g,cutoff=max.dist,width=max.dist/nBins); #plot(v0)#v0 <- variogram(g);#WJ
  ##print(sprintf('print(sum(is propMaxD=%.4f nBins=%d',propMaxD, nBins))#for debugging only
  if(length(unique(v0$id))!=3){
    v0 <- variogram(g,cutoff=max(c(rdist(data[,1:2])))/2)
    if(length(unique(v0$id))!=3){
      v0 <- variogram(g,cutoff=max(c(rdist(data[,1:2]))))
      if(length(unique(v0$id))!=3){
        stop("Error: An expert choice is required to identify the cutoff for the variogram ...")
      }
    }
  }
  v <- fit.lmc(v=v0, g=g, vgm(model = model))
  if(is.matrix(grid) | is.data.frame(grid)){
    grid <- as.data.frame(grid)
    coordinates(grid) <- names(grid)
  }
  else{
    grid <- data.frame(matrix(c(grid),1,2))
    coordinates(grid) <- names(grid)
  }
  out <- predict(v, grid)
  list(
    out.01.pred = out$tr1.pred,
    out.01.var = out$tr1.var,
    out.02.pred = out$tr2.pred,
    out.02.var = out$tr2.var,
    out.12.cov = out$cov.tr1.tr2,
    range_psill=v$model,
    n.sample=ck
  )
}
##
##
.TR_3 <- function(data, grid, model, tr) {
  g.dat <- list()
  ll <- unique(data[, 4])
  for(j in 1:tr){
    g.dat[[j]] <- subset(data,data[,4]==ll[j])
    names(g.dat[[j]])[3] <- paste0(names(g.dat[[j]])[3],ll[j])
    coordinates(g.dat[[j]]) <-
      as.formula(paste0("~", names(g.dat[[j]])[1], "+", names(g.dat[[j]])[2]))
  }
  g <- gstat(id="tr1",formula=as.formula(paste0(names(g.dat[[1]])[1], "~1")),data=g.dat[[1]],set = list(nocheck = 1))
  g <- gstat(g,id="tr2",formula=as.formula(paste0(names(g.dat[[2]])[1], "~1")),data=g.dat[[2]],set = list(nocheck = 1))
  g <- gstat(g,id="tr3",formula=as.formula(paste0(names(g.dat[[3]])[1], "~1")),data=g.dat[[3]],set = list(nocheck = 1))
  rm(g.dat)
  ck <- NULL
  for (k in 1:tr) {
    ck[k] <- length(data[data[, 4] == ll[k], 4])
  }
  (max.dist <- max(c(rdist(data[,1:2])))*propMaxD);  v0 <- variogram(g,cutoff=max.dist,width=max.dist/nBins); #plot(v0)
  #browser()
  if(length(unique(v0$id))!=6){
    v0 <- variogram(g,cutoff=max(c(rdist(data[,1:2])))/2)
    if(length(unique(v0$id))!=6){
      v0 <- variogram(g,cutoff=max(c(rdist(data[,1:2]))))
      if(length(unique(v0$id))!=6){
        stop("Error: An expert choice is required to identify the cutoff for the variogram ...")
      }
    }
  }
  v <- fit.lmc(v=v0, g=g, vgm(model = model))
  if(is.matrix(grid) | is.data.frame(grid)){
    grid <- as.data.frame(grid)
    coordinates(grid) <- names(grid)
  }
  else{
    grid <- data.frame(matrix(c(grid),1,2))
    coordinates(grid) <- names(grid)
  }
  out <- predict(v, grid)
  list(
    out.01.pred = out$tr1.pred,
    out.01.var = out$tr1.var,
    out.02.pred = out$tr2.pred,
    out.02.var = out$tr2.var,
    out.03.pred = out$tr3.pred,
    out.03.var = out$tr3.var,
    out.12.cov = out$cov.tr1.tr2,
    out.13.cov = out$cov.tr1.tr3,
    out.23.cov = out$cov.tr2.tr3,
    range_psill=v$model,
    n.sample=ck
  )
}
##
## convert seconds into min. hour. and day
##
.fnc.time_<-function(t)
{
  #
  if(t < 60){
    t <- round(t,2)
    tt <- paste(t," - Sec.")
    cat(paste("##\n# Elapsed time:",t,"Sec.\n##\n"))
  } 
  #
  if(t < (60*60) && t >= 60){
    t1 <- as.integer(t/60)
    t <- round(t-t1*60,2) 
    tt <- paste(t1," - Mins.",t," - Sec.")
    cat(paste("##\n# Elapsed time:",t1,"Min.",t,"Sec.\n##\n"))
  }
  #
  if(t < (60*60*24) && t >= (60*60)){
    t2 <- as.integer(t/(60*60))
    t <- t-t2*60*60
    t1 <- as.integer(t/60)
    t <- round(t-t1*60,2) 
    tt <- paste(t2," - Hour/s.",t1," - Mins.",t," - Sec.")
    cat(paste("##\n# Elapsed time:",t2,"Hour/s.",t1,"Min.",t,"Sec.\n##\n"))
  }
  #
  if(t >= (60*60*24)){
    t3 <- as.integer(t/(60*60*24))
    t <- t-t3*60*60*24
    t2 <- as.integer(t/(60*60))
    t <- t-t2*60*60
    t1 <- as.integer(t/60)
    t <- round(t-t1*60,2)
    tt <- paste(t3," - Day/s.",t2," - Hour/s.",t1," - Mins.",t," - Sec.")
    cat(paste("##\n# Elapsed time:",t3,"Day/s.",t2,"Hour/s.",t1,"Mins.",t,"Sec.\n##\n"))
  }
  #
  tt
}
##
##################################################################################
##################################################################################


# ----------------------------------------------------------------------------------
# Functions to retrieve national CRS from a proj4 string or spatial file
#
# David Gobbett
# Dec 2018
#
# ----------------------------------------------------------------------------------
# Modifications:
# ----------------------------------------------------------------------------------
#
# ----------------------------------------------------------------------------------
#require(gdalUtils)
#require(rgdal)
#require(stringr)
#require(raster)

getNationalCRSbyProj4 <- function (proj4, nationalCS="") {
    # proj4: Character. A gdal proj4 string
    # nationalCS: See above for national coordinate system names
    
    eAll <- as.data.frame(make_EPSG())
    eMatch <- eAll[which(eAll$prj4 == proj4), ]
    
    national_EPSG <- eMatch[which(str_detect(eMatch$note, nationalCS)),]$code
    if (length(national_EPSG) == 0) {
        outCRS <- CRS(proj4)        # No national proj4 string matches, so make a CRS using the input proj4 string  
    } else if (length(national_EPSG) == 1) {
        outCRS <- CRS(paste0("+init=EPSG:", national_EPSG))
    } else if (length(national_EPSG) > 1) {
        # more than one match. We'll just use the first one and 
        # write a message 
        outCRS <- CRS(paste0("+init=EPSG:", national_EPSG[1]))
        print(paste("nationalCRS.R: Warning: >1 national CS match for proj4:", proj4,"& nationalCS",nationalCS))
    }
    return(outCRS)
}

getNationalCRSfromRasterfile <- function (filename, nationalCS="") {
    # testing:
    #      filename <- Input_Block_Grid_Filename
    #      nationalCS <- "GDA94"
    # filename: Character. A raster dataset filename.
    # nationalCS: See above for national coordinate system names
    proj4 <- gdalsrsinfo(filename, 
                      p=TRUE, V=FALSE, o="proj4", 
                      as.CRS = FALSE, ignore.full_scan = TRUE, verbose = FALSE)
    proj4 <- trimws(paste(proj4, collapse = ''))    # convert to single string and trim
    nationalCRS <- getNationalCRSbyProj4(proj4, nationalCS)
    return(nationalCRS)
}

getRasterCentreWGS84XY <- function(inRaster) {
    # Convert raster extent centroid to WGS84 lat long 
    wgs84epsg <- 4326
    wgs84CRS <- CRS(paste0("+init=EPSG:", wgs84epsg))
    wgs84Ext <- projectExtent(inRaster, wgs84CRS)       # just project the extent, no need to do the whole raster
    x_coord <- (wgs84Ext@extent@xmin + wgs84Ext@extent@xmax)/2
    y_coord <- (wgs84Ext@extent@ymin + wgs84Ext@extent@ymax)/2
    xy_epsg <- wgs84epsg
    return (list("x_coord"=x_coord, "y_coord"= y_coord, "xy_epsg" = xy_epsg))
}

getProjectedCRSForXY <- function (x_coord, y_coord, xy_epsg=4326) {
    # An R implementation of the pyprecag function by the same name
    # returns either a national (Australia & NZ only) CRS or 
    # a UTM CRS
    
    wgs84epsg <- 4326
    # Coordinates need to be in wgs84 so project them
    if (xy_epsg != wgs84epsg) {
        xy <- data.frame(ID = 1:length(x_coord), X = x_coord, Y = y_coord)
        coordinates(xy) <- c("X", "Y")
        
        inCRS = CRS(paste0("+init=EPSG:", xy_epsg))
        outCRS = CRS(paste0("+init=EPSG:", wgs84epsg))
        
        proj4string(xy) <- inCRS
        res <- spTransform(xy, outCRS)
        return (as.data.frame(res))
    } else {
        longitude <- x_coord; latitude <- y_coord
    }
    
    utm_zone <- as.integer(1 + (longitude + 180.0) / 6.0)
    
    # Determines if given latitude is a northern for UTM        1 is northern, 0 is southern
    is_northern <- (latitude > 0.0)
    
    if ((108.0 <= longitude) && (longitude <= 155.0) && 
        (-45.0 <= latitude) && (latitude <= -10.0)) {
        # if in Australia use GDA94 MGA zones otherwise use UTM system
        utm_crs <- CRS(paste0("+init=EPSG:", (28300 + utm_zone)))
    } else if ((166.33 <= longitude) && (longitude <= 178.6) && 
               (-47.4 <= latitude) && (latitude <= -34.0)) {
        # if in NZ use NZGD2000
        # 166.3300, -47.4000, 178.6000, -34.0000
        utm_crs <- CRS(paste0("+init=EPSG:", 2193))
    } else {
        # otherwise use UTM system
        utm_crs <- CRS(paste0("+proj=utm +zone=", utm_zone, 
                              if(!is_northern) " +south",
                              " +datum=WGS84")) 
    }
    
    if (is.projected(utm_crs)) {
        return(utm_crs)   
    } else {
        return(NA)  
    } 
}

##################################################################################
##################################################################################
